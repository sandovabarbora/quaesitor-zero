#!/bin/sh
# Prepare the scenario docs/workflow.tape records.
#
# The recording shows all three steps against the public TPC-DS warehouse. It
# is real end to end, which is only possible because the current generator
# reproduces the recorded example's question set exactly: same warehouse, same
# flags, 20 of 20 ids. So the replies in examples/tpcds/answers.csv really are
# answers to the questions the recording generates, from the frontier-model run
# whose provenance is in answers.provenance.json.
#
# Nothing here is written to make the tool look good. The replies are what the
# model said.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
work=${1:?usage: workflow-setup.sh <dir>}
warehouse=${2:-}
rm -rf "$work"; mkdir -p "$work"; cd "$work"

if [ -n "$warehouse" ]; then
  cp "$warehouse" tpcds.duckdb
elif [ -f "$here/examples/tpcds/tpcds.duckdb" ]; then
  cp "$here/examples/tpcds/tpcds.duckdb" tpcds.duckdb
else
  echo "need the TPC-DS warehouse: python examples/tpcds/build.py" >&2
  exit 1
fi

# Staged where the recording expects them, so the "paste the replies" beat is a
# copy of real answers rather than an invention.
cp "$here/examples/tpcds/answers.csv" .replies.csv
cp "$here/examples/tpcds/review.csv" review.csv
