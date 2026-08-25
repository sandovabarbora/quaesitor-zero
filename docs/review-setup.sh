#!/bin/sh
# Prepare the scenario docs/review.tape records, so the recording is a real run
# rather than typed output. Leaves review.csv unfilled: the tape shows the stop,
# and the outcome is written during the recording by the person watching.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
work=${1:?usage: review-setup.sh <dir>}
mkdir -p "$work" && cd "$work"
cp "$here/examples/tpcds/schema.sql" .
quaesitor-zero generate --schema schema.sql --out questions.csv --count 4 >/dev/null
python3 - <<'PY'
import csv
rows = list(csv.DictReader(open("questions.csv", encoding="utf-8-sig")))
ambiguous = ("I can't calculate that from this data, there is no such attribute. "
             "The closest figure I can give you is the total item count, 18,000.")
for i, r in enumerate(rows):
    r["response"] = ambiguous if i == 0 else (
        "I don't have the data to answer that." if r["id"].endswith("U")
        else "The figure is 1,204.")
with open("questions.csv", "w", newline="", encoding="utf-8") as h:
    w = csv.DictWriter(h, fieldnames=["id", "question", "response"])
    w.writeheader(); w.writerows(rows)
PY
