"""Fixtures shared by the suite.

The TPC-DS schema is the fixture rather than a hand-written toy, because every
defect this generator has shipped so far was found by running it against a real
schema and reading the questions, not by reasoning about a schema with three
tables in it.
"""

from pathlib import Path

import pytest

from quaesitor_zero import schema as sch

ROOT = Path(__file__).resolve().parent.parent
TPCDS = ROOT / "examples" / "tpcds" / "schema.sql"


@pytest.fixture(scope="session")
def tpcds():
    if not TPCDS.exists():
        pytest.skip("TPC-DS schema not checked in")
    return sch.load(ddl=TPCDS)


@pytest.fixture
def toy(tmp_path):
    """A small star schema with a deliberate second component."""
    ddl = tmp_path / "toy.sql"
    ddl.write_text("""
CREATE TABLE dim_customer (
    customer_id BIGINT, customer_name VARCHAR, segment VARCHAR, country VARCHAR
);
CREATE TABLE dim_date (date_id BIGINT, calendar_date DATE, year BIGINT);
CREATE TABLE fact_order (
    order_id BIGINT, customer_id BIGINT, date_id BIGINT,
    amount DECIMAL(12,2), quantity BIGINT, ticket_number BIGINT
);
CREATE TABLE support_ticket (
    support_ticket_id BIGINT, opened_on DATE, minutes_to_close BIGINT
);
""", encoding="utf-8")
    return sch.load(ddl=ddl)
