#!/bin/sh
# Prepare the scenario docs/workflow.tape records.
#
# The recording is real end to end. That works because `generate` against the
# example's own warehouse reproduces the recorded question set exactly: same 20
# ids, same 20 question texts. So the replies in examples/tpcds/answers.csv
# really are answers to the questions the recording generates, from the
# frontier-model run whose provenance is in answers.provenance.json.
#
# It has to be that warehouse. A TPC-DS database generated separately covers a
# different date range, and the families that name a year then name a different
# one, so the replies would be answers to slightly different questions.
# examples/tpcds/build.py makes the right one; it is gitignored because DuckDB
# writes it in seconds.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
work=${1:?usage: workflow-setup.sh <dir>}
warehouse="$here/examples/tpcds/tpcds.duckdb"

[ -f "$warehouse" ] || {
  echo "no warehouse at $warehouse; build it with:" >&2
  echo "  python examples/tpcds/build.py" >&2
  exit 1
}

rm -rf "$work"; mkdir -p "$work"; cd "$work"
cp "$warehouse" tpcds.duckdb
cp "$here/examples/tpcds/schema.sql" .
# Staged where the recording expects them, so the "paste the replies" beat is a
# copy of real answers rather than an invention.
cp "$here/examples/tpcds/answers.csv" .replies.csv
cp "$here/examples/tpcds/review.csv" review.csv
