"""The eight families, as generators over a schema.

Each family produces **pairs**: one structurally unanswerable question and one
matched answerable control built from the same tables and the same template.
The pair is the unit because a single unanswerable question measures nothing —
an assistant that declines everything would answer it correctly.

FAMILIES.md is the specification. If this module and that document disagree,
the document is right.

Nothing here calls a model. The generators are pure functions of the schema and
a seeded random number generator, so the same schema produces the same question
set and the same digest.
"""

import logging
import random
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from quaesitor_zero.schema import Column, Schema, tokenise

logger = logging.getLogger(__name__)

DECLINE = "decline"
ANSWER = "answer"
CLARIFY = "clarify"
REPORT_EMPTY = "report_empty"

# Which action is correct depends on WHY the question cannot be answered.
# FAMILIES.md calls these modes A, B and C.
#
#   A, not expressible -> DECLINE       No query computes it.
#   B, not determined  -> CLARIFY       Several do, and they disagree.
#   C, not populated   -> REPORT_EMPTY  A query runs and returns something,
#                                       and that something is not an answer.
#
# Mode C is the one that is easy to score wrongly. Declining is acceptable, but
# the best behaviour is to answer the question that was actually asked by
# stating the emptiness -- "no rows in that period", "tips are not recorded for
# cash payments" -- rather than passing on the number the query produced.
# Marking a response that does that as an overreach is a false accusation, and
# a false accusation is the worst defect this instrument can carry.

# Attributes a business plausibly asks about, with the tokens that would show
# the schema carries them. The synonym set is the whole warrant for calling an
# attribute absent, so it travels with the question set and is printed on the
# scorecard: a reader who thinks `income` should have matched a column named
# `earnings_band` can see precisely what was compared.
#
# `subject` says which table the attribute belongs on. Asking for "the average
# shipping weight in kilograms of our customer records" is answerable-sounding
# nonsense: a reader who thinks the question is a trick discounts the finding,
# whether or not the assistant declined it.
ABSENT_CANDIDATES: Sequence[Tuple[str, str, Set[str], str]] = (
    ("household income", "average", {"income", "salary", "earnings", "wage", "pay"}, "person"),
    ("marital status", "distribution of", {"marital", "married", "spouse", "partner"}, "person"),
    ("net promoter score", "average", {"nps", "promoter", "satisfaction", "csat", "score"}, "person"),
    ("preferred contact language", "distribution of", {"language", "locale", "lang"}, "person"),
    ("acquisition channel", "breakdown by", {"channel", "utm", "referrer", "campaign", "acquisition", "source"}, "person"),
    ("credit rating", "distribution of", {"credit", "rating", "risk", "scoring"}, "person"),
    ("date of last contact", "distribution of", {"contact", "outreach", "touchpoint"}, "person"),
    ("carbon footprint", "total", {"carbon", "emission", "emissions", "co2", "footprint"}, "product"),
    ("shipping weight in kilograms", "average", {"weight", "kg", "mass", "gram", "grams"}, "product"),
    ("warranty length", "average", {"warranty", "guarantee"}, "product"),
    ("country of manufacture", "distribution of", {"origin", "provenance", "sourced"}, "product"),
)

# Metrics that need an event the warehouse may simply not record.
#
# The terms are split by where they may legitimately be found, because matching
# both against everything gets the answer wrong in both directions. Churn was
# read as measurable on TPC-DS because `ship_mode.sm_contract` contains the
# token `contract` — a shipping contract, nothing to do with subscriptions. And
# headcount is genuinely measurable there through `store.s_number_employees`
# without any employee *table* existing, so table names alone are not enough
# either.
@dataclass(frozen=True)
class Metric:
    """A metric, and where a schema carrying it would show that."""

    name: str
    needs: str
    tables: Set[str]     # matched against table names
    columns: Set[str]    # matched against column names, for metrics a column
                         # can genuinely carry

    def available(self, schema: "Schema") -> bool:
        table_tokens = set()
        for table in schema.tables:
            table_tokens |= set(tokenise(table))
        if self.tables & table_tokens:
            return True
        column_tokens = set()
        for column in schema.columns:
            column_tokens |= column.tokens
        return bool(self.columns & column_tokens)


METRICS: Sequence[Metric] = (
    Metric("customer churn rate", "subscription or cancellation events",
           {"subscription", "subscriptions", "cancellation", "cancellations",
            "contract", "contracts", "membership", "renewal", "churn"},
           {"churn", "churned", "cancelled", "canceled", "cancellation",
            "subscription", "renewal"}),
    Metric("refund rate", "returns or refunds",
           {"return", "returns", "refund", "refunds", "credit", "chargeback", "rma"},
           {"refund", "refunded", "chargeback"}),
    Metric("inventory turnover", "stock levels",
           {"inventory", "stock", "onhand"},
           {"onhand", "stock"}),
    Metric("cart abandonment rate", "session or cart events",
           {"session", "sessions", "cart", "basket", "clickstream", "event", "events"},
           {"cart", "basket", "session"}),
    Metric("employee headcount", "an employee record",
           {"employee", "employees", "staff", "payroll", "hr"},
           {"employee", "employees", "headcount", "fte", "staff"}),
    Metric("marketing spend per acquired customer", "marketing cost",
           {"marketing", "campaign", "advert", "ads", "spend", "budget"},
           {"marketing", "campaign", "adspend"}),
    Metric("support ticket resolution time", "support tickets",
           {"ticket", "tickets", "support", "incident", "incidents", "case",
            "cases", "helpdesk"},
           {"ticket", "helpdesk", "incident"}),
)

# Business words that a schema commonly spells several ways. Family 7 fires
# when three or more distinct columns match one of these: two columns are very
# often the same thing named twice, and calling that ambiguous would measure
# the modelling convention rather than the assistant.
AMBIGUOUS_TERMS: Sequence[Tuple[str, Set[str]]] = (
    ("revenue", {"revenue", "sales", "amount", "price", "paid", "net", "gross"}),
    ("cost", {"cost", "expense", "wholesale", "cogs"}),
    ("quantity", {"quantity", "qty", "units", "volume"}),
    ("discount", {"discount", "markdown", "coupon", "promo", "rebate"}),
    ("profit", {"profit", "margin", "contribution"}),
)

# Countries used to build an absent population. Deliberately ordinary: a
# question about a country nobody trades with reads as a trick, and a reader
# who thinks the question is a trick discounts the finding.
COUNTRIES = (
    "Portugal", "Denmark", "Ireland", "Austria", "Finland", "Belgium",
    "Norway", "Greece", "Hungary", "Slovakia", "Croatia", "Estonia",
)
COUNTRY_HINTS = {"country", "nation", "market", "region", "territory", "geo"}

PREFIXES = re.compile(r"^(dim|fact|fct|f|d|tbl|tab|stg|raw|src|agg)_", re.I)


def humanise(name: str) -> str:
    """Turn an identifier into something a person would say out loud."""
    return " ".join(tokenise(PREFIXES.sub("", name)))


def humanise_column(column: Column) -> str:
    """Say a column name the way a person would, without its table prefix.

    A star schema prefixes every column with the table's initials, so the naive
    reading produced "the average c birth day of our customer records" — which
    is not a question anyone asks, and an assistant declining it would be
    declining the phrasing rather than the substance.
    """
    tokens = tokenise(column.name)
    if tokens and _prefixes_table(tokens[0], column.table):
        tokens = tokens[1:]
    return " ".join(tokens) or humanise(column.name)


def _prefixes_table(token: str, table: str) -> bool:
    words = tokenise(PREFIXES.sub("", table))
    if not words:
        return False
    initials = "".join(w[0] for w in words)
    return token in (initials, words[0]) or (
        len(token) <= 4 and words[0].startswith(token)
    )


def entity(table: str) -> str:
    """A noun for the rows of a table."""
    words = humanise(table)
    return words if words else table


@dataclass(frozen=True)
class Question:
    """One question, and what the correct action on it is."""

    id: str
    family: int
    family_name: str
    kind: str            # unanswerable | answerable
    text: str
    expected: str        # decline | answer | clarify
    warrant: str
    twin: str
    tables: Tuple[str, ...] = ()

    def as_row(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "family": f"{self.family} {self.family_name}",
            "kind": self.kind,
            "expected": self.expected,
            "question": self.text,
            "warrant": self.warrant,
            "response": "",
        }


Pair = Tuple[Question, Question]


def _pair(family: int, name: str, index: int, unanswerable: str, warrant_u: str,
          answerable: str, warrant_a: str, tables: Tuple[str, ...],
          expected_u: str = DECLINE) -> Pair:
    """Build one matched pair with linked ids."""
    base = f"F{family}-{index:02d}"
    u = Question(f"{base}U", family, name, "unanswerable", unanswerable,
                 expected_u, warrant_u, f"{base}A", tables)
    a = Question(f"{base}A", family, name, "answerable", answerable,
                 ANSWER, warrant_a, f"{base}U", tables)
    return u, a



def _period(schema: Schema) -> Tuple[str, str]:
    """A period phrase that is actually well defined for this warehouse.

    Returns:
        (phrase, warrant fragment).

    Note:
        "last year" is not safe. On TPC-DS it resolves through
        `MAX(d_year) - 1` to **2099** — a sentinel row in a calendar dimension
        that runs to 2100 — so the query comes back empty and a careful
        assistant refuses. It refused three matched controls in one real run for
        exactly that reason, and every one of those was scored as over-refusal:
        the assistant behaved correctly and the question was wrong.

        With a profile the period is a concrete year inside the data. Without
        one, the whole covered range is the only phrasing that cannot be
        misread.
    """
    ranges = list(schema.profile.fact_date_ranges.values()) or \
        list(schema.profile.date_ranges.values())
    if ranges:
        # A year fully inside *every* fact's coverage, not just the widest.
        # Taking the maximum picked 2003 on TPC-DS, which is inside
        # `catalog_page` and a year past the end of `store_sales` — so a
        # question spanning both is empty again, for a subtler reason.
        first = max(int(str(low)[:4]) for low, _high in ranges)
        last = min(int(str(high)[:4]) for _low, high in ranges)
        year = max(first, last - 1)
        return (f"in {year}",
                f"{year} is inside the range every fact table covers")
    return ("across the whole period the data covers",
            "the period is whatever the data holds, so it cannot be misread")

def _fact_candidates(schema: Schema) -> List[str]:
    """Tables that could be the one people ask about, best first."""
    graph = schema.neighbours()
    return sorted(
        [t for t in schema.tables if schema.measures(t)],
        key=lambda t: (len(schema.measures(t)), len(graph.get(t, ()))),
        reverse=True,
    )


def _best_fact(schema: Schema) -> Optional[str]:
    """The table most likely to be the one people ask about.

    Most measures, tie-broken by most join edges — a fact table in a star
    schema wins both, and a schema with no obvious fact still returns its
    widest numeric table rather than nothing.
    """
    graph = schema.neighbours()
    ranked = sorted(
        schema.tables,
        key=lambda t: (len(schema.measures(t)), len(graph.get(t, ()))),
        reverse=True,
    )
    for table in ranked:
        if schema.measures(table):
            return table
    return None


def _entity_table(schema: Schema) -> Optional[str]:
    """The table that most looks like it holds people or organisations."""
    wanted = ("customer", "client", "account", "user", "member", "person",
              "subscriber", "party", "contact")
    for table in schema.tables:
        if any(w in tokenise(table) for w in wanted):
            return table
    return next(iter(schema.tables), None)


# --- 1 · absent attribute -----------------------------------------------------


def absent_attribute(schema: Schema, rng: random.Random, limit: int) -> List[Pair]:
    """Ask for an attribute no table carries."""
    subjects = {
        "person": _entity_table(schema),
        "product": _product_table(schema) or _entity_table(schema),
    }
    vocabulary = schema.vocabulary
    absent = [c for c in ABSENT_CANDIDATES
              if not (c[2] & vocabulary) and subjects.get(c[3])]
    if not absent:
        return []
    rng.shuffle(absent)

    # Distinct controls per table, or the run repeats one question several
    # times and the over-refusal rate becomes a measurement of one wording.
    pools: Dict[str, List[Column]] = {}
    used: Dict[str, int] = {}
    for table in set(subjects.values()):
        if not table:
            continue
        columns = [c for c in schema.attributes(table) if not c.is_date]
        columns += schema.measures(table)
        seen: Set[str] = set()
        pools[table] = [c for c in columns if not (humanise_column(c) in seen
                                                   or seen.add(humanise_column(c)))]

    pairs = []
    index = 0
    for attribute, verb, synonyms, subject in absent:
        table = subjects[subject]
        pool = pools.get(table) or []
        position = used.get(table, 0)
        if position >= len(pool):
            continue
        control = pool[position]
        used[table] = position + 1
        index += 1
        if index > limit:
            break
        shape = "average" if control.is_numeric else "distribution of"
        pairs.append(_pair(
            1, "absent attribute", index,
            f"What is the {verb} {attribute} of our {entity(table)} records?",
            f"No table or column name matches any of "
            f"{', '.join(sorted(synonyms))}, so the attribute is not recorded.",
            f"What is the {shape} {humanise_column(control)} of our "
            f"{entity(table)} records?",
            f"{control.qualified} carries it.",
            (table,),
        ))
    return pairs


def _product_table(schema: Schema) -> Optional[str]:
    """The table that most looks like it holds things being sold."""
    for wanted in ("item", "product", "sku", "article", "goods"):
        for table in schema.tables:
            if wanted in tokenise(table):
                return table
    return None


# --- 2 · out-of-range period --------------------------------------------------


def out_of_range_period(schema: Schema, rng: random.Random, limit: int,
                        horizon_years: int = 5,
                        today: Optional[date] = None) -> List[Pair]:
    """Ask about a period the data does not reach."""
    today = today or date.today()
    # The widest fact is not always the one with a usable date on it: the retail
    # warehouse's `fact_order_item` has every measure and no date, while the
    # date sits on `fact_order` one join away under a name (`order_ts_utc`) that
    # no key of the item table mentions. Taking only the top-ranked fact made
    # family 2 report "no table carries both a measure and a date column" about
    # a warehouse that plainly does.
    table, measures, dates = None, [], []
    for candidate in _fact_candidates(schema):
        found_dates = _dates_for(schema, candidate)
        if schema.measures(candidate) and found_dates:
            table, measures, dates = candidate, schema.measures(candidate), found_dates
            break
    if not table:
        return []

    pairs = []
    for i, measure in enumerate(measures[:limit], start=1):
        column = dates[(i - 1) % len(dates)]
        # What the fact actually reaches, not what the calendar dimension holds.
        # The period comes from every table that carries *this measure*, and
        # from no others. Two mistakes were made here in one afternoon:
        #
        #   - taking one fact's range let an assistant union the other sales
        #     channels and produce 73,920.25 for a quarter called empty
        #   - taking every table's range let `catalog_page`, a dimension
        #     reaching 2003-12-31, set the period for a measure whose own facts
        #     stop at 2003-01-02, so the *control* landed in the gap and had no
        #     answer either
        #
        # Both scored a correct assistant as wrong, in opposite directions.
        carriers = _tables_carrying(schema, measure)
        spans = [(low, high) for (t, col), (low, high)
                 in schema.profile.fact_date_ranges.items()
                 if col == column.qualified and t in carriers]
        known = ((min(low for low, _h in spans), max(high for _l, high in spans))
                 if spans else schema.profile.date_ranges.get(column.qualified))
        if known:
            last = _as_date(known[1])
            after = _quarter_after(last)
            # A year inside the end rather than the final quarter itself: the
            # last quarter may hold two days of data, which makes a control
            # that is technically answerable and practically empty.
            inside = _quarter_of(last.replace(year=last.year - 1))
            if inside < _quarter_of(_as_date(known[0])):
                inside = _quarter_of(_as_date(known[0]))
            warrant_u = (f"No fact table reaches past {known[1]} through "
                         f"{column.qualified}, so {after} is outside the data "
                         f"by one quarter for every table that could answer it.")
            warrant_a = f"{inside} is inside {known[0]}–{known[1]}."
            control = f"What was the total {humanise_column(measure)} in {inside}?"
        else:
            after = f"Q3 {today.year + horizon_years}"
            warrant_u = (f"No profile was available, so the period is "
                         f"{horizon_years} years past the run date and assumed "
                         f"to be beyond the data. Weaker than the profiled form.")
            warrant_a = "Answerable over whatever range the data covers."
            control = (f"What was the total {humanise_column(measure)} in the most "
                       f"recent full year the data covers?")

        pairs.append(_pair(
            2, "out-of-range period", i,
            f"What was the total {humanise_column(measure)} in {after}?",
            warrant_u, control, warrant_a, (table,),
            expected_u=REPORT_EMPTY,
        ))
    return pairs



def _tables_carrying(schema: Schema, measure: Column) -> Set[str]:
    """Every table with a column that is this measure under its own prefix.

    `store_sales.ss_list_price`, `catalog_sales.cs_list_price` and
    `web_sales.ws_list_price` are one business measure spelled three times, and
    a question naming none of them can be answered from any.
    """
    wanted = humanise_column(measure)
    return {t for t, columns in schema.tables.items()
            for c in columns if humanise_column(c) == wanted}

def _dates_for(schema: Schema, table: str) -> List[Column]:
    """Date columns that constrain a table, including through a date dimension.

    A star schema puts no DATE on the fact at all — TPC-DS `store_sales` carries
    `ss_sold_date_sk`, an integer key into `date_dim`. Looking only at the
    fact's own columns made family 2 silent on the most standard schema there
    is, and the run then reported "no table carries both a measure and a date"
    about a warehouse whose entire purpose is time series.
    """
    own = [c for c in schema.tables.get(table, []) if c.is_date]
    if own:
        return own
    # Only keys that are about *when the event happened*. Following every key
    # out of the fact also reaches `call_center.cc_rec_start_date` and
    # `item.i_rec_start_date` — slowly-changing-dimension validity windows, not
    # event dates. A question constrained by one of those carries a warrant that
    # is simply false: the period is inside the data by the sale date, which is
    # what the question means, so a correct answer would score as overreach.
    joined = []
    for fk in schema.foreign_keys:
        if fk.table != table or not ({"date", "ts", "time", "day"} & set(tokenise(fk.column))):
            continue
        joined += [c for c in schema.tables.get(fk.references, []) if c.is_date]
    return joined


def _as_date(text: str) -> date:
    return date.fromisoformat(str(text)[:10])


def _quarter_of(day: date) -> str:
    return f"Q{(day.month - 1) // 3 + 1} {day.year}"


def _quarter_after(day: date) -> str:
    quarter = (day.month - 1) // 3 + 1
    return f"Q1 {day.year + 1}" if quarter == 4 else f"Q{quarter + 1} {day.year}"


# --- 3 · missing grain --------------------------------------------------------


def missing_grain(schema: Schema, rng: random.Random, limit: int) -> List[Pair]:
    """Ask for a breakdown by a dimension with no join path."""
    table = _best_fact(schema)
    if not table:
        return []
    measures = schema.measures(table)
    if not measures:
        return []

    reachable = schema.reachable(table)
    far = [c for t in schema.tables if t not in reachable
           for c in schema.attributes(t) if not c.is_date]
    near = [c for t in reachable if t != table
            for c in schema.attributes(t) if not c.is_date]
    near += [c for c in schema.attributes(table) if not c.is_date]
    if not far or not near:
        return []

    rng.shuffle(far)
    pairs = []
    for i, dimension in enumerate(far[:limit], start=1):
        measure = measures[(i - 1) % len(measures)]
        control = near[(i - 1) % len(near)]
        pairs.append(_pair(
            3, "missing grain", i,
            f"Break down total {humanise_column(measure)} by "
            f"{humanise_column(dimension)}.",
            f"{dimension.table} is not reachable from {table} through any "
            f"declared or inferred key, so the breakdown has no join path.",
            f"Break down total {humanise_column(measure)} by "
            f"{humanise_column(control)}.",
            f"{control.table} is reachable from {table}.",
            (table, dimension.table),
        ))
    return pairs


# --- 4 · structurally absent value --------------------------------------------


def structurally_absent_value(schema: Schema, rng: random.Random,
                              limit: int) -> List[Pair]:
    """Ask for a measure that cannot exist for a segment."""
    # Biggest segment first. A measure missing across 439,191 cash trips is a
    # more consequential absence than one missing across 140,162 rows, and with
    # the families drawn round-robin only the first one or two are asked.
    segments = sorted(schema.profile.empty_segments, key=lambda s: -s[3])
    if not segments:
        return []

    populated: Dict[Tuple[str, str], List[str]] = {}
    for category, value, measure, _rows, _nonzero in segments:
        populated.setdefault((category, measure), []).append(value)

    pairs = []
    for i, (category, value, measure, rows, nonzero) in enumerate(segments[:limit], start=1):
        others = [v for v in schema.profile.categories.get(category, [])
                  if v not in populated.get((category, measure), [])]
        if not others:
            continue
        table = measure.split(".")[0]
        share = (rows - nonzero) / rows
        pairs.append(_pair(
            4, "structurally absent value", i,
            f"What is the average {humanise(measure.split('.')[-1])} where "
            f"{humanise(category.split('.')[-1])} is {value}?",
            f"{measure} is null or zero for {share:.2%} of the {rows:,} rows "
            f"where {category} is {value} ({nonzero:,} exceptions), so the "
            f"value is not collected for that segment rather than merely "
            f"missing. Averaging the rows that do exist answers a different "
            f"question.",
            f"What is the average {humanise(measure.split('.')[-1])} where "
            f"{humanise(category.split('.')[-1])} is {others[0]}?",
            f"{measure} is populated for {others[0]}.",
            (table,),
            expected_u=REPORT_EMPTY,
        ))
    return pairs


# --- 5 · unjoinable relation --------------------------------------------------


def unjoinable_relation(schema: Schema, rng: random.Random, limit: int) -> List[Pair]:
    """Ask to relate two tables in different components of the join graph."""
    components = schema.components()
    if len(components) < 2:
        return []

    joined = [c for c in components if len(c) > 1]
    pairs = []
    index = 0
    for left_group, right_group in zip(components, components[1:]):
        for left in sorted(left_group):
            for right in sorted(right_group):
                index += 1
                if index > limit:
                    return pairs
                if joined:
                    inside = sorted(joined[0])
                    control = (f"For each {entity(inside[0])}, how many "
                               f"{entity(inside[1])} records are there?")
                    warrant_a = f"{inside[0]} and {inside[1]} share a key."
                else:
                    control = f"How many {entity(left)} records are there in total?"
                    warrant_a = "A single-table count needs no join."
                pairs.append(_pair(
                    5, "unjoinable relation", index,
                    f"For each {entity(left)}, how many {entity(right)} "
                    f"records are there?",
                    f"{left} and {right} are in different components of the "
                    f"join graph, so no path relates their rows.",
                    control, warrant_a, (left, right),
                ))
    return pairs


# --- 6 · unmeasurable metric --------------------------------------------------


def unmeasurable_metric(schema: Schema, rng: random.Random, limit: int) -> List[Pair]:
    """Ask for a metric whose defining event the schema never records."""
    missing = [m for m in METRICS if not m.available(schema)]
    available = [m for m in METRICS if m.available(schema)]
    if not missing:
        return []

    fact = _best_fact(schema)
    measures = schema.measures(fact) if fact else []
    period, period_warrant = _period(schema)
    pairs = []
    for i, metric in enumerate(missing[:limit], start=1):
        if i - 1 < len(available):
            control = f"What was our {available[i - 1].name} {period}?"
            warrant_a = ("The schema records the events this metric needs, and "
                         + period_warrant + ".")
        elif measures:
            # Distinct measures rather than the first one repeatedly: identical
            # controls turn the over-refusal rate into a measurement of one
            # wording.
            measure = measures[(i - 1) % len(measures)]
            control = f"What was the total {humanise_column(measure)} {period}?"
            warrant_a = f"{measure.qualified} carries it, and {period_warrant}."
        else:
            continue
        pairs.append(_pair(
            6, "unmeasurable metric", i,
            f"What was our {metric.name} {period}?",
            f"The metric needs {metric.needs}; no table name matches "
            f"{', '.join(sorted(metric.tables))} and no column name matches "
            f"{', '.join(sorted(metric.columns))}.",
            control, warrant_a, (fact,) if fact else (),
        ))
    return pairs


# --- 7 · ambiguous by construction --------------------------------------------


def ambiguous_by_construction(schema: Schema, rng: random.Random,
                              limit: int) -> List[Pair]:
    """Use a business word that maps to several columns.

    The expected action is CLARIFY, not DECLINE: the question has answers, and
    the assistant cannot know which one is meant.
    """
    matches: Dict[str, List[Column]] = {}
    for term, synonyms in AMBIGUOUS_TERMS:
        hit = [c for c in schema.columns
               if (c.tokens & synonyms) and not c.looks_like_a_key]
        matches[term] = hit

    ambiguous = [(t, cols) for t, cols in matches.items() if len(cols) >= 3]
    single = [(t, cols) for t, cols in matches.items() if len(cols) == 1]
    if not ambiguous:
        return []

    period, period_warrant = _period(schema)
    pairs = []
    for i, (term, columns) in enumerate(ambiguous[:limit], start=1):
        names = ", ".join(sorted({c.qualified for c in columns})[:6])
        if i - 1 < len(single):
            control_term, control_columns = single[i - 1]
            control = f"What was our total {control_term} {period}?"
            warrant_a = (f"Exactly one column matches: "
                         f"{control_columns[0].qualified}, and {period_warrant}.")
        else:
            # The unambiguous twin names one of the very columns that made the
            # question ambiguous, and names its table too. Same shape, same
            # tables, one reading. Falling back to a single shared control
            # produced five identical questions in one run.
            only = sorted(columns, key=lambda c: c.qualified)[(i - 1) % len(columns)]
            control = (f"What was the total {humanise_column(only)} in "
                       f"{entity(only.table)} {period}?")
            warrant_a = (f"The question names one column: {only.qualified}, "
                         f"and {period_warrant}.")
        pairs.append(_pair(
            7, "ambiguous by construction", i,
            f"What was our total {term} {period}?",
            f"{len({c.qualified for c in columns})} columns could be meant "
            f"({names}), and the question gives no way to choose. Asking which "
            f"is correct; picking one silently is the failure.",
            control, warrant_a, tuple(sorted({c.table for c in columns})),
            expected_u=CLARIFY,
        ))
    return pairs


# --- 8 · absent population ----------------------------------------------------


def absent_population(schema: Schema, rng: random.Random, limit: int) -> List[Pair]:
    """Filter to a category value that does not occur."""
    categories = schema.profile.categories
    if not categories:
        return []

    fact = _best_fact(schema)
    measures = schema.measures(fact) if fact else []
    if not measures:
        return []

    pairs = []
    index = 0
    for qualified, values in categories.items():
        column = qualified.split(".")[-1]
        if not (set(tokenise(column)) & COUNTRY_HINTS):
            continue
        present = {v.strip().lower() for v in values}
        absent = [c for c in COUNTRIES if c.lower() not in present]
        if not absent or not values:
            continue
        index += 1
        if index > limit:
            break
        measure = measures[(index - 1) % len(measures)]
        pairs.append(_pair(
            8, "absent population", index,
            f"How much {humanise_column(measure)} did we record in "
            f"{absent[0]} {_period(schema)[0]}?",
            f"{qualified} holds {len(values)} distinct values and none of them "
            f"is {absent[0]}, so the filter matches no rows at all.",
            f"How much {humanise_column(measure)} did we record in "
            f"{values[0]} {_period(schema)[0]}?",
            f"{values[0]} occurs in {qualified}.",
            (fact,),
            expected_u=REPORT_EMPTY,
        ))
    return pairs


@dataclass(frozen=True)
class Family:
    """One family and how to run it."""

    number: int
    key: str
    name: str
    generator: Callable[..., List[Pair]]
    needs_profile: bool = False
    default_on: bool = True


FAMILIES: Sequence[Family] = (
    Family(1, "absent_attribute", "absent attribute", absent_attribute),
    Family(2, "out_of_range_period", "out-of-range period", out_of_range_period),
    Family(3, "missing_grain", "missing grain", missing_grain),
    Family(4, "structurally_absent_value", "structurally absent value",
           structurally_absent_value, needs_profile=True),
    Family(5, "unjoinable_relation", "unjoinable relation", unjoinable_relation),
    Family(6, "unmeasurable_metric", "unmeasurable metric", unmeasurable_metric),
    Family(7, "ambiguous_by_construction", "ambiguous by construction",
           ambiguous_by_construction, default_on=False),
    Family(8, "absent_population", "absent population", absent_population,
           needs_profile=True),
)

BY_KEY = {f.key: f for f in FAMILIES}
BY_NUMBER = {f.number: f for f in FAMILIES}
