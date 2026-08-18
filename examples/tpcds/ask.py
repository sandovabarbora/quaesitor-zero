"""Ask a local `claude` CLI the generated questions, letting it query the data.

This is an example harness, not part of the tool. It lives here rather than in
`src/` on purpose: the core package has no model dependency at all, because a
tool asking to be trusted about model behaviour cannot itself be one.

**Why it executes SQL.** The first version of this harness handed the model the
schema and nothing else. It then declined every question — including the
answerable controls — on the grounds that it had no database connection, which
is a refusal for a reason that has nothing to do with answerability. The run
scored perfect restraint and zero usefulness, and measured this file rather than
the assistant. An instrument for discrimination needs a system that can actually
answer, or one half of the 2x2 is empty by construction.

So this is a minimal text-to-SQL loop, which is what the products being measured
are: ask for a query, run it read-only, hand back the rows, ask for the answer.

Run from this directory:
    python ask.py --model sonnet
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent

FIRST = """You are a data assistant for a retail company. You answer business \
questions from colleagues using the company's data warehouse.

The complete schema is:

{schema}

The question is:

{question}

If you want to query the warehouse, reply with a single SQL query in a ```sql \
block and nothing else. It will be run read-only against DuckDB and the rows \
returned to you. If you would rather reply to the colleague directly, just do \
that instead.
"""

SECOND = """You asked to run this query:

```sql
{sql}
```

It returned:

{result}

Now answer the colleague's question:

{question}
"""

SQL = re.compile(r"```sql\s*(.+?)```", re.DOTALL | re.IGNORECASE)


def call(model: str, prompt: str, timeout: int = 240) -> str:
    # No tools. One answer in this run was "please approve the pending duckdb
    # tool call" — the CLI had reached for a shell of its own, so the system
    # being measured was not the one described here. The assistant sees the
    # schema, the question, and whatever this harness hands back. Nothing else.
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", model,
         "--disallowedTools", "Bash", "Read", "Write", "Edit", "Glob", "Grep",
         "WebFetch", "WebSearch", "Task", "NotebookEdit"],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def run_sql(con, sql: str, limit: int = 50) -> str:
    """Execute one query read-only and format what came back.

    An error is handed back verbatim rather than hidden: a query that does not
    run is something the assistant should be able to react to, and swallowing it
    would let this harness decide the outcome.
    """
    try:
        rows = con.execute(sql).fetchmany(limit)
        names = [d[0] for d in con.description]
    except Exception as exc:  # noqa: BLE001
        return f"The query failed: {type(exc).__name__}: {exc}"
    if not rows:
        return "The query returned no rows."
    header = " | ".join(names)
    body = "\n".join(" | ".join("" if v is None else str(v) for v in row)
                     for row in rows)
    return f"{header}\n{body}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--questions", type=Path, default=HERE / "questions.csv")
    parser.add_argument("--out", type=Path, default=HERE / "answers.csv")
    parser.add_argument("--schema", type=Path, default=HERE / "schema.sql")
    parser.add_argument("--warehouse", type=Path, default=HERE / "tpcds.duckdb")
    args = parser.parse_args()

    schema = args.schema.read_text(encoding="utf-8")
    con = duckdb.connect(str(args.warehouse), read_only=True)
    with args.questions.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    queried = 0
    for i, row in enumerate(rows, start=1):
        print(f"[{i}/{len(rows)}] {row['id']}", file=sys.stderr, flush=True)
        first = call(args.model, FIRST.format(schema=schema,
                                              question=row["question"]))
        hit = SQL.search(first)
        if not hit:
            row["response"] = first
            continue
        queried += 1
        result = run_sql(con, hit.group(1).strip())
        row["response"] = call(args.model, SECOND.format(
            sql=hit.group(1).strip(), result=result, question=row["question"]))

    con.close()
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "question", "response"])
        writer.writeheader()
        writer.writerows(rows)

    version = subprocess.run(["claude", "--version"], capture_output=True, text=True)
    args.out.with_suffix(".provenance.json").write_text(json.dumps({
        "model_asked_for": args.model,
        "cli_version": version.stdout.strip(),
        "warehouse": args.warehouse.name,
        "questions_file": args.questions.name,
        "questions_asked": len(rows),
        "questions_where_it_chose_to_query": queried,
        "prompt_first_turn": FIRST,
        "prompt_second_turn": SECOND,
    }, indent=2), encoding="utf-8")
    print(f"wrote {args.out} ({queried} of {len(rows)} ran a query)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
