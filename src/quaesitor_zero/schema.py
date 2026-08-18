"""Read a schema, and optionally profile the data behind it.

The schema is loaded by executing the DDL into an in-memory DuckDB and then
introspecting the catalogue, rather than by parsing SQL here. That buys a real
parser instead of a regex that is wrong in ways nobody notices, and it makes
failure legible: a statement DuckDB cannot execute is recorded and reported,
because a table that silently failed to load makes families 3 and 5 emit fewer
questions while looking exactly like a schema that had nothing to say.

Nothing in this module sends anything anywhere. The profile runs read-only
against a local file and keeps only aggregates.

References:
    - DuckDB metadata functions: https://duckdb.org/docs/stable/sql/meta/duckdb_table_functions
    - DuckDB Python API: https://duckdb.org/docs/stable/clients/python/overview
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

import duckdb

logger = logging.getLogger(__name__)

DATE_TYPES = ("DATE", "TIMESTAMP", "DATETIME")
NUMERIC_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
                 "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL")
TEXT_TYPES = ("VARCHAR", "CHAR", "TEXT", "STRING")

# Dialect differences that stop a warehouse's own DDL from loading. Kept
# deliberately short: a rewrite that changes what a column means would produce
# questions about a schema the customer does not have, which is worse than
# refusing to load. Everything here is a spelling, not a semantic.
DIALECT = (
    (re.compile(r"`([^`]*)`"), r'"\1"'),                       # MySQL quoting
    (re.compile(r"\bNUMBER\s*\(", re.I), "DECIMAL("),          # Oracle, Snowflake
    (re.compile(r"\bVARCHAR2\s*\(", re.I), "VARCHAR("),        # Oracle
    (re.compile(r"\bNVARCHAR\d*\s*\(", re.I), "VARCHAR("),     # SQL Server
    (re.compile(r"\bSTRING\b", re.I), "VARCHAR"),              # Hive, Databricks
    (re.compile(r"\bDATETIME2?\b", re.I), "TIMESTAMP"),
    (re.compile(r"\bAUTOINCREMENT\b", re.I), ""),
    (re.compile(r"\bUNSIGNED\b", re.I), ""),
    (re.compile(r"\bENGINE\s*=\s*\w+", re.I), ""),
    (re.compile(r"\bDISTSTYLE\s+\w+", re.I), ""),
    (re.compile(r"\b(DISTKEY|SORTKEY|CLUSTER\s+BY)\s*\([^)]*\)", re.I), ""),
    (re.compile(r"\bCOLLATE\s+\w+", re.I), ""),
)

# A token that is a key rather than an attribute. Families that ask for an
# attribute must not pick one of these: "what is the customer's sk" is a
# question nobody asks and its refusal would measure nothing.
KEY_TOKENS = frozenset({"id", "key", "sk", "pk", "fk", "uuid", "guid", "hash"})

# Identifiers that only read as keys at the *end* of a name. `ss_ticket_number`
# is an order identifier and summing it is meaningless — the generator asked
# for "the total order number in Q3 2031", which is a trick question rather than
# a measurement. But `s_number_employees` is a real measure, and a plain token
# test would throw it away, so the test is on the suffix.
KEY_SUFFIXES = ("number", "num", "no", "code", "seq", "sequence", "nbr")


@dataclass(frozen=True)
class Column:
    """One column, with the type reduced to the three kinds that matter here."""

    table: str
    name: str
    type: str

    @property
    def qualified(self) -> str:
        return f"{self.table}.{self.name}"

    @property
    def is_date(self) -> bool:
        return any(t in self.type.upper() for t in DATE_TYPES)

    @property
    def is_numeric(self) -> bool:
        return any(t in self.type.upper() for t in NUMERIC_TYPES)

    @property
    def is_text(self) -> bool:
        return any(t in self.type.upper() for t in TEXT_TYPES)

    @property
    def tokens(self) -> FrozenSet[str]:
        return frozenset(tokenise(self.name))

    @property
    def looks_like_a_key(self) -> bool:
        if self.tokens & KEY_TOKENS:
            return True
        tokens = tokenise(self.name)
        return bool(tokens) and tokens[-1] in KEY_SUFFIXES


@dataclass(frozen=True)
class ForeignKey:
    """One edge of the join graph, declared or inferred."""

    table: str
    column: str
    references: str
    referenced_column: str
    inferred: bool = False


@dataclass
class Profile:
    """What was found by looking at the data, rather than at the schema.

    Empty when the run had no connection. Every field is an aggregate; no row
    of customer data is stored, printed, or written to the question set.
    """

    row_counts: Dict[str, int] = field(default_factory=dict)
    date_ranges: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    # (fact table, qualified date column) -> the range that fact actually
    # reaches. A calendar dimension is not evidence of coverage: TPC-DS ships a
    # `date_dim` spanning 1900 to 2100 while its sales cover about five years,
    # so reading the dimension alone would ask about Q1 2101 — true, useless,
    # and it would miss the quarter just past the end of the data, which is the
    # question worth asking.
    fact_date_ranges: Dict[Tuple[str, str], Tuple[str, str]] = field(default_factory=dict)
    categories: Dict[str, List[str]] = field(default_factory=dict)
    empty_segments: List[Tuple[str, str, str, int, int]] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return bool(self.row_counts)


@dataclass
class Schema:
    """A schema as the generators see it."""

    tables: Dict[str, List[Column]]
    foreign_keys: List[ForeignKey]
    skipped: List[str] = field(default_factory=list)
    profile: Profile = field(default_factory=Profile)
    source: str = ""

    @property
    def columns(self) -> List[Column]:
        return [c for cols in self.tables.values() for c in cols]

    @property
    def vocabulary(self) -> Set[str]:
        """Every token appearing in a table or column name.

        Used to decide that an attribute is absent. Tokens rather than whole
        names, so `annual_income` is found when the question asks about income.
        """
        words = set()
        for table, cols in self.tables.items():
            words |= set(tokenise(table))
            for c in cols:
                words |= c.tokens
        return words

    def measures(self, table: str) -> List[Column]:
        """Numeric columns of a table that are plausibly measures, not keys."""
        return [c for c in self.tables.get(table, [])
                if c.is_numeric and not c.looks_like_a_key]

    # Free text is not a dimension. "What is the distribution of item desc?"
    # over a column of thousands of distinct sentences is a question with no
    # useful answer, and an assistant that hedges on it is scored as refusing
    # something it could have answered.
    FREE_TEXT = ("desc", "description", "comment", "comments", "note", "notes",
                 "text", "body", "url", "email", "address", "name")

    def attributes(self, table: str) -> List[Column]:
        """Descriptive columns of a table: text or date, and not a key.

        With a profile, only columns known to have few distinct values count as
        text dimensions; without one, names that read as free text are dropped.
        """
        found = []
        for c in self.tables.get(table, []):
            if c.looks_like_a_key or not (c.is_text or c.is_date):
                continue
            if c.is_text:
                if self.profile.categories:
                    if c.qualified not in self.profile.categories:
                        continue
                elif set(tokenise(c.name)) & set(self.FREE_TEXT):
                    continue
            found.append(c)
        return found

    def neighbours(self) -> Dict[str, Set[str]]:
        """The join graph as an undirected adjacency map."""
        graph: Dict[str, Set[str]] = {t: set() for t in self.tables}
        for fk in self.foreign_keys:
            if fk.table in graph and fk.references in graph:
                graph[fk.table].add(fk.references)
                graph[fk.references].add(fk.table)
        return graph

    def components(self) -> List[Set[str]]:
        """Connected components of the join graph, largest first.

        A schema with no declared and no inferred keys returns one component
        per table, which is the honest reading: nothing in the schema says any
        two of them can be joined. Family 5 then has plenty to say and family 3
        has none, and both facts are printed rather than averaged away.
        """
        graph = self.neighbours()
        seen: Set[str] = set()
        found: List[Set[str]] = []
        for start in self.tables:
            if start in seen:
                continue
            stack, group = [start], set()
            while stack:
                node = stack.pop()
                if node in group:
                    continue
                group.add(node)
                stack.extend(graph[node] - group)
            seen |= group
            found.append(group)
        return sorted(found, key=len, reverse=True)

    def reachable(self, table: str) -> Set[str]:
        for group in self.components():
            if table in group:
                return group
        return {table}

    def digest(self) -> str:
        """Stable fingerprint of the schema the questions were built from.

        Sorted and normalised, so the same warehouse read twice digests the
        same, and a column added between two runs does not.
        """
        payload = {
            "tables": {t: sorted((c.name, c.type) for c in cols)
                       for t, cols in sorted(self.tables.items())},
            "foreign_keys": sorted(
                (fk.table, fk.column, fk.references, fk.referenced_column)
                for fk in self.foreign_keys
            ),
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def tokenise(name: str) -> List[str]:
    """Split an identifier into lower-case word tokens.

    Args:
        name: A table or column name, in snake_case, camelCase or plain.

    Returns:
        The tokens, lower-cased.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t]


def split_statements(sql: str) -> List[str]:
    """Split a DDL script into statements.

    Args:
        sql: The script.

    Returns:
        Statements, without trailing semicolons, comments removed.

    Note:
        Splitting on `;` alone breaks on a semicolon inside a string literal or
        a comment, which in DDL usually means inside a COMMENT clause — and the
        two halves then both fail to parse, so one stray character costs two
        tables. The quote and comment states are tracked for that reason.
    """
    out, current = [], []
    in_single = in_double = in_line = in_block = False
    i = 0
    while i < len(sql):
        ch, nxt = sql[i], sql[i + 1:i + 2]
        if in_line:
            if ch == "\n":
                in_line = False
                current.append(ch)
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 1
        elif in_single:
            current.append(ch)
            if ch == "'":
                in_single = False
        elif in_double:
            current.append(ch)
            if ch == '"':
                in_double = False
        elif ch == "-" and nxt == "-":
            in_line = True
            i += 1
        elif ch == "/" and nxt == "*":
            in_block = True
            i += 1
        elif ch == "'":
            in_single = True
            current.append(ch)
        elif ch == '"':
            in_double = True
            current.append(ch)
        elif ch == ";":
            out.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    out.append("".join(current))
    return [s.strip() for s in out if s.strip()]


def _normalise(statement: str) -> str:
    for pattern, replacement in DIALECT:
        statement = pattern.sub(replacement, statement)
    return statement


def _label(statement: str) -> str:
    """A short name for a statement, for the skipped list."""
    hit = re.search(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:\w+\s+)?TABLE\s+"
                    r"(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"`]+)", statement, re.I)
    if hit:
        return hit.group(1).strip('"`')
    return " ".join(statement.split()[:4])


def load_ddl(path: Path) -> Schema:
    """Load a schema from a DDL file.

    Args:
        path: File holding CREATE TABLE statements.

    Returns:
        The schema, with any statement DuckDB refused recorded in `skipped`.

    Raises:
        ValueError: If no table could be created at all.
    """
    text = path.read_text(encoding="utf-8")
    con = duckdb.connect(":memory:")
    skipped: List[str] = []

    for statement in split_statements(text):
        if not re.match(r"\s*CREATE\b", statement, re.I):
            continue
        try:
            con.execute(_normalise(statement))
        except Exception as exc:  # noqa: BLE001 — the message is the product here
            skipped.append(f"{_label(statement)}: {type(exc).__name__}: {exc}")
            logger.warning("Could not load %s", _label(statement))

    schema = _introspect(con, source=str(path))
    schema.skipped = skipped
    con.close()
    if not schema.tables:
        raise ValueError(
            f"No table could be created from {path}. "
            + ("First failure: " + skipped[0] if skipped else "No CREATE TABLE found.")
        )
    return schema


def load_warehouse(path: Path) -> Schema:
    """Load a schema from an existing DuckDB file, read-only.

    Args:
        path: The database file.

    Returns:
        The schema. Call `profile` separately to look at the data.
    """
    con = duckdb.connect(str(path), read_only=True)
    schema = _introspect(con, source=str(path))
    con.close()
    return schema


def _introspect(con: duckdb.DuckDBPyConnection, source: str) -> Schema:
    """Read tables, columns and declared foreign keys out of a catalogue."""
    tables: Dict[str, List[Column]] = {}
    # Restricted to the catalogue's own non-internal tables. Reading
    # duckdb_columns() alone also returns DuckDB's `pg_catalog` and
    # `sqlite_master` compatibility views, and the generator cheerfully wrote a
    # question about breaking down `pg_class` — a schema that is real, present,
    # and not the customer's.
    rows = con.execute(
        "SELECT c.table_name, c.column_name, c.data_type "
        "FROM duckdb_columns() c "
        "JOIN duckdb_tables() t "
        "  ON t.table_name = c.table_name AND t.schema_name = c.schema_name "
        "WHERE NOT t.internal "
        "ORDER BY c.table_name, c.column_index"
    ).fetchall()
    for table, column, dtype in rows:
        tables.setdefault(table, []).append(Column(table, column, dtype))

    keys: List[ForeignKey] = []
    try:
        constraints = con.execute(
            "SELECT table_name, constraint_column_names, referenced_table, "
            "referenced_column_names FROM duckdb_constraints() "
            "WHERE constraint_type = 'FOREIGN KEY'"
        ).fetchall()
    except Exception:  # noqa: BLE001 — older DuckDB has no referenced_table
        constraints = []
        logger.info("This DuckDB does not expose referenced_table; "
                    "declared foreign keys will be read as none")
    for table, cols, ref_table, ref_cols in constraints:
        for i, col in enumerate(cols or []):
            ref_col = (ref_cols or [None] * len(cols))[i] if ref_cols else None
            keys.append(ForeignKey(table, col, ref_table, ref_col or col))

    return Schema(tables=tables, foreign_keys=keys, source=source)


def _abbreviates(token: str, table: str) -> bool:
    """Is this token the table's own prefix rather than part of the subject?

    `ss_customer_sk` in `store_sales` carries `ss` for the table, not for what
    the key points at. Left in, every column stem starts with noise and nothing
    matches anything.
    """
    words = tokenise(PREFIX_STRIP.sub("", table))
    if not words:
        return False
    initials = "".join(w[0] for w in words)
    return token in (initials, words[0]) or (
        len(token) <= 4 and words[0].startswith(token)
    )


def _stem(column: Column) -> Tuple[str, ...]:
    """What a key column is a key *to*, with table prefix and key noun removed.

    `store_sales.ss_customer_sk` -> ('customer',)
    `customer.c_customer_sk`     -> ('customer',)
    `store_sales.ss_sold_date_sk`-> ('sold', 'date')
    """
    tokens = [t for t in tokenise(column.name) if t not in KEY_TOKENS]
    if tokens and _abbreviates(tokens[0], column.table):
        tokens = tokens[1:]
    return tuple(tokens)


PREFIX_STRIP = re.compile(r"^(dim|fact|fct|tbl|tab|stg|raw|src|agg)_", re.I)


def infer_keys(schema: Schema) -> List[ForeignKey]:
    """Infer join edges from naming, for schemas that declare none.

    Args:
        schema: The loaded schema.

    Returns:
        Inferred foreign keys, excluding any already declared.

    Note:
        Analytical warehouses usually declare no constraints at all — TPC-DS
        itself declares none — so without this the join graph is empty, every
        table is its own component, and families 3 and 5 end up measuring the
        modelling convention rather than the assistant.

        Matching is on the stem rather than the whole name, because a star
        schema prefixes its columns per table: `ss_customer_sk` and
        `c_customer_sk` are the same key spelled twice, and an exact-name rule
        finds nothing at all on the most standard schema there is. The target's
        stem has to be a **suffix** of the source's, so `ss_sold_date_sk` reaches
        `date_dim.d_date_sk` while `ss_customer_sk` does not.

        Every inferred edge is printed on the scorecard. An edge that does not
        really exist turns an unjoinable question into a joinable one, and would
        score a correct refusal as overreach.
    """
    declared = {(fk.table, fk.column) for fk in schema.foreign_keys}

    # Where each stem can be reached: a table whose own name carries the stem
    # and which has a key column of that stem is the target. Each target also
    # registers the alias its prefix spells out, because `store_sales.ss_cdemo_sk`
    # points at `customer_demographics.cd_demo_sk` — the prefix `cd` is part of
    # the reference, and dropping it collides with `household_demographics.hd_demo_sk`
    # so that both fact keys would resolve to whichever table was read first.
    targets: Dict[Tuple[str, ...], Tuple[str, str]] = {}
    for table, columns in schema.tables.items():
        table_tokens = set(tokenise(PREFIX_STRIP.sub("", table)))
        for column in columns:
            if not column.looks_like_a_key:
                continue
            stem = _stem(column)
            if not stem or not all(
                any(_akin(s, t) for t in table_tokens) for s in stem
            ):
                continue
            raw = [t for t in tokenise(column.name) if t not in KEY_TOKENS]
            aliases = [stem]
            if len(raw) == len(stem) + 1:
                # `household_demographics.hd_demo_sk` is referenced as both
                # `hd_demo_sk` and `hdemo_sk`, so both spellings are registered.
                # Without the second, `ss_hdemo_sk` falls through to the
                # approximate pass and lands on `customer_demographics` —
                # a wrong edge between two tables that really are distinct.
                aliases.append((raw[0] + stem[0],) + stem[1:])
                aliases.append((raw[0][0] + stem[0],) + stem[1:])
            for alias in aliases:
                targets.setdefault(alias, (table, column.name))

    found: List[ForeignKey] = []
    for table, columns in schema.tables.items():
        for column in columns:
            if (table, column.name) in declared or not column.looks_like_a_key:
                continue
            stem = _stem(column)
            if not stem:
                continue
            # Longest suffix first: `bill_customer` should reach `customer`
            # rather than stopping at a one-token coincidence. Exact before
            # approximate, so `cdemo` resolves before `demo` is considered.
            hit = None
            for start in range(len(stem)):
                hit = targets.get(stem[start:])
                if hit and hit[0] != table:
                    break
                hit = None
            if hit is None:
                hit = _approximate(stem, targets, table)
            if hit:
                found.append(ForeignKey(table, column.name, hit[0], hit[1],
                                        inferred=True))
    return found


def _akin(left: str, right: str) -> bool:
    """Are two name tokens the same word spelled at different lengths?

    `addr` and `address` are; `id` and `item` are not. Four characters is the
    floor because shorter prefixes match almost anything, and a wrong edge is
    worse than a missing one: it turns a question with no join path into one
    that has one, and then scores a correct refusal as overreach.
    """
    if left == right:
        return True
    if min(len(left), len(right)) < 4:
        return False
    return (left.startswith(right) or right.startswith(left)
            or left.endswith(right) or right.endswith(left))


def _approximate(stem: Tuple[str, ...], targets: Dict[Tuple[str, ...], Tuple[str, str]],
                 table: str) -> Optional[Tuple[str, str]]:
    """Find a target whose stem is a near-suffix of this one."""
    for start in range(len(stem)):
        tail = stem[start:]
        for candidate, hit in targets.items():
            if hit[0] == table or len(candidate) != len(tail):
                continue
            if all(_akin(a, b) for a, b in zip(tail, candidate)):
                return hit
    return None


def profile(schema: Schema, path: Path, max_categories: int = 40,
            min_rows: int = 100) -> Profile:
    """Look at the data behind a schema, read-only, keeping only aggregates.

    Args:
        schema: The loaded schema.
        path: DuckDB file to read.
        max_categories: Treat a text column as categorical below this many
            distinct values.
        min_rows: Ignore a segment smaller than this, so a single stray row
            does not become a finding.

    Returns:
        The profile. Families 4 and 8 are empty without one, and family 2 falls
        back to a horizon assumption.
    """
    con = duckdb.connect(str(path), read_only=True)
    result = Profile()
    try:
        for table, columns in schema.tables.items():
            try:
                (count,) = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            except Exception:  # noqa: BLE001 — a view over a missing file
                logger.info("Skipping %s: not readable", table)
                continue
            result.row_counts[table] = count
            if not count:
                continue

            for column in columns:
                if column.is_date:
                    lo, hi = con.execute(
                        f'SELECT MIN("{column.name}"), MAX("{column.name}") '
                        f'FROM "{table}"'
                    ).fetchone()
                    if lo is not None and hi is not None:
                        result.date_ranges[column.qualified] = (str(lo), str(hi))
                elif not column.looks_like_a_key and (
                        column.is_text or _is_integer(column)):
                    # Integer codes are categories in every real warehouse:
                    # NYC taxi records `payment_type` as 1, 2, 3, and reading
                    # only text columns made family 4 blind to the single most
                    # compelling case the method has.
                    limit = max_categories if column.is_text else 20
                    (distinct,) = con.execute(
                        f'SELECT COUNT(DISTINCT "{column.name}") FROM "{table}"'
                    ).fetchone()
                    if 1 < distinct <= limit:
                        values = con.execute(
                            f'SELECT DISTINCT "{column.name}" FROM "{table}" '
                            f'WHERE "{column.name}" IS NOT NULL '
                            f'ORDER BY 1 LIMIT {max_categories}'
                        ).fetchall()
                        result.categories[column.qualified] = [str(v[0]) for v in values]

            result.empty_segments += _empty_segments(
                con, schema, table, result, min_rows
            )

        result.fact_date_ranges = _joined_date_ranges(con, schema)
    finally:
        con.close()
    return result


def _joined_date_ranges(con: duckdb.DuckDBPyConnection,
                        schema: Schema) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """How far each fact table actually reaches through its date dimension.

    Returns:
        (fact table, qualified date column) -> (first, last).
    """
    found: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for fk in schema.foreign_keys:
        dates = [c for c in schema.tables.get(fk.references, []) if c.is_date]
        if not dates or fk.table == fk.references:
            continue
        for column in dates:
            try:
                low, high = con.execute(
                    f'SELECT MIN(d."{column.name}"), MAX(d."{column.name}") '
                    f'FROM "{fk.table}" f '
                    f'JOIN "{fk.references}" d ON f."{fk.column}" = d."{fk.referenced_column}"'
                ).fetchone()
            except Exception:  # noqa: BLE001 — a key that does not really join
                logger.info("Could not follow %s.%s to %s", fk.table, fk.column,
                            fk.references)
                continue
            if low is None or high is None:
                continue
            key = (fk.table, column.qualified)
            existing = found.get(key)
            if not existing or (str(low), str(high)) != existing:
                found[key] = (str(min(str(low), existing[0])) if existing else str(low),
                              str(max(str(high), existing[1])) if existing else str(high))
    return found


def _empty_segments(con: duckdb.DuckDBPyConnection, schema: Schema, table: str,
                    found: Profile, min_rows: int,
                    threshold: float = 0.995) -> List[Tuple[str, str, str, int]]:
    """Find (category, measure) pairs where the measure effectively cannot exist.

    Returns:
        Tuples of (category column, category value, measure column, rows).

    Note:
        `threshold` is the share of the segment that has to be null or zero, and
        it is 99.5% rather than 100% because real data is never 100%. The NYC
        cash-tip case — the clearest instance of this family anywhere — has 128
        nonzero rows in 439,191 cash trips, presumably fat fingers at the meter.
        Demanding absolute emptiness found nothing in any of six real
        warehouses, which is the opposite of what this family is for.

        The segment also has to be big enough to be a segment. Anything weaker
        is a sparse column, which is a different and much less interesting
        thing: this family is about a value the business never collects, not a
        value it collects badly.
    """
    out = []
    measures = [c for c in schema.measures(table)]
    categories = [c for c in schema.tables[table]
                  if c.qualified in found.categories]
    for category in categories:
        for measure in measures:
            # A column is not a segment of itself. Pairing `passenger_count`
            # with `passenger_count` produced "the average passenger count for
            # 0 passenger count" — true, trivial, and it crowded out the real
            # finding in the same table.
            if measure.name == category.name:
                continue
            # A column with a handful of distinct values is a code, not a
            # measure. `date_dim.d_dow` is 0 for every Sunday, which is a
            # perfect structural absence and a completely worthless question:
            # it asked "what is the average dow where day name is Sunday" and
            # displaced the real finding in the same warehouse.
            if measure.qualified in found.categories:
                continue
            rows = con.execute(
                f'SELECT "{category.name}", COUNT(*) AS n, '
                f'  COUNT(*) FILTER (WHERE COALESCE("{measure.name}", 0) <> 0) AS nonzero '
                f'FROM "{table}" WHERE "{category.name}" IS NOT NULL '
                f'GROUP BY 1 HAVING n >= {min_rows} '
                f'AND nonzero <= n * {1 - threshold}'
            ).fetchall()
            for value, n, nonzero in rows:
                out.append((category.qualified, str(value), measure.qualified, n,
                            nonzero))
    return out


def _is_integer(column: Column) -> bool:
    return any(t in column.type.upper()
               for t in ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT"))


def load(ddl: Optional[Path] = None, warehouse: Optional[Path] = None,
         infer: bool = True, do_profile: bool = True) -> Schema:
    """Load a schema from whichever source was given.

    Args:
        ddl: DDL file, or None.
        warehouse: DuckDB file, or None.
        infer: Add naming-based join edges where none are declared.
        do_profile: Look at the data, when there is data to look at.

    Returns:
        The schema, profiled if a warehouse was given.

    Raises:
        ValueError: If neither source was given.
    """
    if warehouse:
        schema = load_warehouse(warehouse)
    elif ddl:
        schema = load_ddl(ddl)
    else:
        raise ValueError("Give either a DDL file or a warehouse")

    if infer:
        inferred = infer_keys(schema)
        schema.foreign_keys = schema.foreign_keys + inferred
        logger.info("Join graph: %d declared, %d inferred edges",
                    len(schema.foreign_keys) - len(inferred), len(inferred))

    if warehouse and do_profile:
        schema.profile = profile(schema, warehouse)
        logger.info("Profiled %d tables, %d date ranges, %d empty segments",
                    len(schema.profile.row_counts), len(schema.profile.date_ranges),
                    len(schema.profile.empty_segments))
    return schema
