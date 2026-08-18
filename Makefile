.PHONY: example test install

install:
	uv venv && uv pip install -e ".[dev]"

test:
	.venv/bin/python -m pytest tests/ -q

# The whole worked example, from a schema nobody here wrote to a scorecard.
# Reproducible with no model access: the answers are checked in, and DuckDB
# generates the warehouse locally in seconds.
#
# It generates from the **warehouse**, not from schema.sql. The checked-in
# answers were collected against the profiled question set, and generating from
# the DDL alone produces different questions — it asked about Q3 2031 while the
# answers are about Q3 2003, so every response was scored against a question
# nobody had put to the assistant.
#
# `--review` is passed because one response needs a person and a person read it.
# That decision is checked in too, so the example reproduces exactly rather than
# stopping to ask again — and so anybody who disagrees with the reading can see
# it, change one cell, and get a different scorecard.
example:
	test -f examples/tpcds/tpcds.duckdb || .venv/bin/python examples/tpcds/build.py
	.venv/bin/quaesitor-zero generate \
	  --warehouse examples/tpcds/tpcds.duckdb \
	  --out examples/tpcds/questions.csv \
	  --include-ambiguous
	.venv/bin/quaesitor-zero score \
	  --answers examples/tpcds/answers.csv \
	  --key examples/tpcds/questions.key.json \
	  --review examples/tpcds/review.csv \
	  --out examples/tpcds/scorecard.html \
	  --assistant "Claude Sonnet 5, text-to-SQL over TPC-DS"
	@echo "open examples/tpcds/scorecard.html"
