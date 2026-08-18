"""Tests for reading a schema and inferring its join graph."""

import pytest

from quaesitor_zero.schema import (
    Column, load_ddl, split_statements, tokenise,
)


def test_tokenise_splits_snake_and_camel():
    assert tokenise("ss_ext_sales_price") == ["ss", "ext", "sales", "price"]
    assert tokenise("extSalesPrice") == ["ext", "sales", "price"]


def test_split_statements_survives_a_semicolon_in_a_string():
    """One stray character inside a COMMENT used to cost two tables.

    Splitting on `;` alone breaks the statement in half, and both halves then
    fail to parse — so a schema loses tables for a reason no message explains.
    """
    sql = "CREATE TABLE a (x VARCHAR DEFAULT 'one; two'); CREATE TABLE b (y INT);"
    assert len(split_statements(sql)) == 2


def test_split_statements_drops_comments():
    sql = "-- a comment; with a semicolon\nCREATE TABLE a (x INT);"
    statements = split_statements(sql)
    assert len(statements) == 1
    assert "comment" not in statements[0]


def test_a_statement_that_does_not_load_is_reported_not_swallowed(tmp_path):
    """A table that silently failed to load makes families 3 and 5 emit fewer
    questions while looking exactly like a schema with nothing to say."""
    ddl = tmp_path / "broken.sql"
    ddl.write_text("CREATE TABLE good (x INT);\n"
                   "CREATE TABLE bad (x NOT A TYPE AT ALL);\n", encoding="utf-8")
    schema = load_ddl(ddl)
    assert "good" in schema.tables
    assert len(schema.skipped) == 1
    assert "bad" in schema.skipped[0]


def test_no_table_at_all_is_an_error_rather_than_an_empty_run(tmp_path):
    ddl = tmp_path / "empty.sql"
    ddl.write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ValueError, match="No table"):
        load_ddl(ddl)


def test_dialect_spellings_load(tmp_path):
    ddl = tmp_path / "other.sql"
    ddl.write_text(
        "CREATE TABLE `sales` (amount NUMBER(12,2), name VARCHAR2(50), "
        "note STRING, created DATETIME);", encoding="utf-8")
    schema = load_ddl(ddl)
    assert set(c.name for c in schema.tables["sales"]) == {
        "amount", "name", "note", "created"}


def test_duckdb_own_catalogue_views_are_not_part_of_the_schema(tpcds):
    """`pg_class` is real, present, and not the customer's.

    Reading duckdb_columns() alone returned 60 tables for a 24-table schema and
    the generator wrote a question about breaking down `pg_class`.
    """
    assert len(tpcds.tables) == 24
    assert not [t for t in tpcds.tables if t.startswith(("pg_", "sqlite_", "duckdb_"))]


def test_a_trailing_number_is_a_key_but_a_leading_one_is_a_measure():
    """`ss_ticket_number` is an identifier; `s_number_employees` is a measure.

    Summing the first produced "the total order number in Q3 2031", which is a
    trick question rather than a measurement, and a reader who thinks a question
    is a trick discounts the finding whatever the assistant did with it.
    """
    assert Column("store_sales", "ss_ticket_number", "BIGINT").looks_like_a_key
    assert not Column("store", "s_number_employees", "BIGINT").looks_like_a_key


def test_tpcds_is_one_component_once_keys_are_inferred(tpcds):
    """TPC-DS declares no foreign keys at all.

    Without inference every table is its own component, family 5 fires on every
    pair, and the run reports that the most standard schema in the industry
    cannot join anything — which is a fact about the tool, not the warehouse.
    """
    assert len(tpcds.components()) == 1
    assert sum(1 for fk in tpcds.foreign_keys if fk.inferred) > 50


def test_the_two_demographics_tables_do_not_collide(tpcds):
    """`ss_cdemo_sk` and `ss_hdemo_sk` point at different tables.

    Both stems reduce to `demo`, so the first-registered table won both and the
    graph gained an edge that does not exist.
    """
    edges = {(fk.column, fk.references) for fk in tpcds.foreign_keys
             if fk.table == "store_sales"}
    assert ("ss_cdemo_sk", "customer_demographics") in edges
    assert ("ss_hdemo_sk", "household_demographics") in edges


def test_digest_is_stable_and_sensitive(tmp_path, toy):
    same = toy.digest()
    assert same == toy.digest()
    ddl = tmp_path / "changed.sql"
    ddl.write_text("CREATE TABLE dim_customer (customer_id BIGINT);", encoding="utf-8")
    assert load_ddl(ddl).digest() != same
