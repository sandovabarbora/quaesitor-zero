"""The two commands, and a third that needs nothing of your own.

    quaesitor-zero demo
    ... or, on your own assistant ...
    quaesitor-zero generate --schema schema.sql --out questions.csv
    ... ask your assistant the questions, paste each response into the CSV ...
    quaesitor-zero score --answers questions.csv --out scorecard.html

`demo` scores a worked example bundled inside the package. It exists because
the first question anyone has is what the scorecard looks like, and answering
it used to require a schema, an assistant and twenty pasted responses. It runs
the same read, classify, score and report path as `score` — a demo that took a
shortcut past the real code would be showing something the tool does not do.

There is no `run` command, and that is the design rather than an omission.
Running it would need credentials for an assistant whose API is different in
every product, and it would take the person who asked out of the loop — the
whole conversion mechanism of this tool is that somebody reads the answers.

References:
    - argparse: https://docs.python.org/3/library/argparse.html
"""

import argparse
import csv
import importlib.resources
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from quaesitor_zero import __version__, generate as gen, report, schema as sch
from quaesitor_zero.classify import (
    Lexicon, apply_review, classify_all,
)
from quaesitor_zero.families import FAMILIES
from quaesitor_zero.score import score as run_score

logger = logging.getLogger(__name__)

REVIEW_FIELDS = ("id", "question", "response", "rules_matched", "outcome")


def _read_answers(path: Path) -> Dict[str, str]:
    """Read the responses out of the answers CSV.

    Args:
        path: The CSV the operator filled in.

    Returns:
        Question id to response text.

    Raises:
        ValueError: If the file has no `id` or no `response` column — a
            spreadsheet round-trip renames columns more often than anyone
            expects, and silently reading zero responses would produce a
            scorecard saying the assistant never answered anything.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = [f.strip().lower() for f in (reader.fieldnames or [])]
        if "id" not in fields or "response" not in fields:
            raise ValueError(
                f"{path} needs an `id` and a `response` column; found: "
                f"{', '.join(reader.fieldnames or ['nothing'])}"
            )
        out = {}
        for row in reader:
            clean = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
            if clean.get("id"):
                out[clean["id"].strip()] = clean.get("response", "")
    return out


def _write_review(path: Path, scores, responses: Dict[str, str]) -> int:
    """Write the rows a person has to read, and say how many there are."""
    rows = [r for r in scores.rows if r.outcome == "unclear"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "id": row.question_id,
                "question": row.text,
                "response": responses.get(row.question_id, ""),
                "rules_matched": row.evidence,
                "outcome": "",
            })
    return len(rows)


def _read_review(path: Path) -> Dict[str, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return {
            (row.get("id") or "").strip(): (row.get("outcome") or "").strip()
            for row in reader if (row.get("id") or "").strip()
        }


def cmd_generate(args: argparse.Namespace) -> int:
    schema = sch.load(
        ddl=args.schema,
        warehouse=args.warehouse,
        infer=not args.no_infer_keys,
        do_profile=not args.no_profile,
    )
    logger.info("Schema: %d tables, %d columns, %d join edges",
                len(schema.tables), len(schema.columns), len(schema.foreign_keys))
    if schema.skipped:
        print(f"warning: {len(schema.skipped)} DDL statements did not load:",
              file=sys.stderr)
        for line in schema.skipped:
            print(f"  {line}", file=sys.stderr)

    question_set = gen.generate(
        schema,
        count=args.count,
        seed=args.seed,
        include=(["ambiguous_by_construction"] if args.include_ambiguous else []),
        exclude=args.exclude or (),
        horizon_years=args.horizon_years,
    )
    key_path = gen.write(question_set, args.out)

    print(f"{len(question_set.unanswerable)} unanswerable questions and "
          f"{len(question_set.answerable)} matched controls")
    for number, count in sorted(question_set.per_family.items()):
        print(f"  family {number}: {count}")
    for name, why in question_set.empty_families.items():
        print(f"  (nothing from {name}: {why})")
    print()
    print(f"questions: {args.out}")
    print(f"key:       {key_path}  — keep this, the scorer needs it, and it "
          f"is deliberately not in the CSV")
    if len(question_set.unanswerable) < args.count:
        print(f"\nnote: asked for {args.count}, this schema supported "
              f"{len(question_set.unanswerable)}", file=sys.stderr)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    key_path = args.key or args.answers.with_suffix(".key.json")
    if not key_path.exists():
        print(f"error: no key file at {key_path}. It is written next to the "
              f"questions CSV by `generate`; pass --key if you moved it.",
              file=sys.stderr)
        return 2

    key = gen.read_key(key_path)
    responses = _read_answers(args.answers)
    known = {q["id"] for q in key["questions"]}
    unknown = set(responses) - known
    if unknown:
        print(f"warning: {len(unknown)} ids in the answers file are not in the "
              f"key and were ignored: {', '.join(sorted(unknown)[:5])}",
              file=sys.stderr)

    lexicon = Lexicon.load(args.lexicon)
    classifications = classify_all(
        {qid: text for qid, text in responses.items() if qid in known}, lexicon
    )

    if args.review and args.review.exists():
        classifications = apply_review(classifications, _read_review(args.review))

    scores = run_score(key["questions"], responses, classifications)

    # The human confirmation pass. A tool that guesses at the responses it
    # cannot read, and then prints a rate to two significant figures, is doing
    # the exact thing it was built to detect.
    if scores.unclear and not args.skip_review:
        # Never write over the file the operator filled in. Passing --review
        # and still having unclear rows used to overwrite that same path with
        # blank outcomes, so a second run silently destroyed the readings a
        # person had already made — including, once, the one decision the whole
        # worked example turns on.
        if args.review and args.review.exists():
            review_path = args.review.with_name(
                args.review.stem + ".todo" + args.review.suffix)
        else:
            review_path = args.review or args.answers.with_name("review.csv")
        count = _write_review(review_path, scores, responses)
        print(f"{count} responses carry evidence of more than one thing and "
              f"need a person to read them.\n")
        print(f"  1. open {review_path}")
        print(f"  2. put `answered`, `declined`, `clarified` or "
              f"`reported_empty` in the `outcome` column")
        print(f"     (`reported_empty` = it gave the figure and said the "
              f"figure is not an answer — no rule can assign that one, only "
              f"you can)")
        print(f"  3. re-run with --review {review_path}\n")
        print("Or pass --skip-review to leave them out of every rate; the "
              "scorecard will say how many were excluded.", file=sys.stderr)
        return 3

    lexicon_note = (f"rules from {args.lexicon}" if args.lexicon
                    else "built-in English rules")
    report.write(scores, key, args.out, args.assistant, lexicon_note)

    print(f"silent overreach {scores.overreach}/{scores.measured_unanswerable}"
          f"   over-refusal {scores.over_refusal}/{scores.measured_answerable}")
    if scores.balanced_accuracy is not None:
        print(f"balanced accuracy {scores.balanced_accuracy:.0%}   "
              f"coverage {scores.coverage:.0%}")
    if scores.unclear or scores.missing:
        print(f"excluded from every rate: {scores.missing} empty, "
              f"{scores.unclear} unreadable")
    print(f"\nscorecard: {args.out}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Score a bundled worked example, so the scorecard can be seen with no setup.

    The example is a real run on the public TPC-DS schema: twenty questions, a
    frontier model's answers, and one human reading of the response that
    carried evidence of more than one thing. `_example/answers.provenance.json`
    records which model, which harness version and the exact prompts, because a
    worked example whose provenance is not stated is a screenshot.

    It runs the same read, classify, score and report path as `score` against
    files shipped inside the package, so `uvx quaesitor-zero demo` needs
    nothing of your own.
    """
    example = importlib.resources.files("quaesitor_zero") / "_example"
    with importlib.resources.as_file(example / "questions.key.json") as key_path, \
            importlib.resources.as_file(example / "answers.csv") as answers_path, \
            importlib.resources.as_file(example / "review.csv") as review_path:
        key = gen.read_key(key_path)
        responses = _read_answers(answers_path)
        known = {q["id"] for q in key["questions"]}
        lexicon = Lexicon.load(None)
        classifications = classify_all(
            {qid: text for qid, text in responses.items() if qid in known},
            lexicon,
        )
        classifications = apply_review(classifications, _read_review(review_path))
        scores = run_score(key["questions"], responses, classifications)
        report.write(scores, key, args.out,
                     "a frontier model \u00b7 TPC-DS (worked example)",
                     "built-in English rules")

    print(f"silent overreach {scores.overreach}/{scores.measured_unanswerable}"
          f"   over-refusal {scores.over_refusal}/{scores.measured_answerable}")
    if scores.balanced_accuracy is not None:
        print(f"balanced accuracy {scores.balanced_accuracy:.0%}   "
              f"coverage {scores.coverage:.0%}")
    print(f"\nscorecard: {args.out}   \u2014 a worked example on public TPC-DS data")
    print("\nRun it on your own assistant:")
    print("  quaesitor-zero generate --schema your_schema.sql --out questions.csv")
    print("  # ask your assistant the questions, paste each response into the CSV")
    print("  quaesitor-zero score --answers questions.csv --out scorecard.html")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quaesitor-zero",
        description="Does your assistant say \"I don't know\" when it cannot know?",
    )
    parser.add_argument("--version", action="version",
                        version=f"quaesitor-zero {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="build a question set from a schema")
    source = g.add_argument_group("schema source")
    source.add_argument("--schema", type=Path, metavar="DDL",
                        help="file of CREATE TABLE statements")
    source.add_argument("--warehouse", type=Path, metavar="DUCKDB",
                        help="DuckDB file, opened read-only; enables families "
                             "4 and 8 and the strong form of family 2")
    g.add_argument("--out", type=Path, default=Path("questions.csv"),
                   help="where the question CSV goes (default: questions.csv)")
    g.add_argument("--count", type=int, default=10,
                   help="unanswerable questions to aim for; each is paired "
                        "with a matched control (default: 10)")
    g.add_argument("--seed", type=int,
                   help="random seed (default: derived from the schema, so the "
                        "same schema gives the same questions)")
    g.add_argument("--include-ambiguous", action="store_true",
                   help="add family 7, ambiguous by construction, which is off "
                        "by default")
    g.add_argument("--exclude", nargs="*", metavar="FAMILY",
                   choices=[f.key for f in FAMILIES],
                   help="family keys to leave out")
    g.add_argument("--no-infer-keys", action="store_true",
                   help="use only declared foreign keys; families 3 and 5 will "
                        "usually then have nothing to say")
    g.add_argument("--no-profile", action="store_true",
                   help="do not read any data, even with a warehouse given")
    g.add_argument("--horizon-years", type=int, default=5,
                   help="how far past today family 2 asks when there is no "
                        "profile (default: 5)")
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("score", help="score an answers file into a scorecard")
    s.add_argument("--answers", type=Path, required=True,
                   help="the question CSV with the response column filled in")
    s.add_argument("--key", type=Path,
                   help="key file (default: the answers file with .key.json)")
    s.add_argument("--out", type=Path, default=Path("scorecard.html"))
    s.add_argument("--assistant", default="",
                   help="what to call the system on the scorecard")
    s.add_argument("--lexicon", type=Path,
                   help="JSON of classification rules, to score responses in "
                        "another language")
    s.add_argument("--review", type=Path,
                   help="review CSV with a person's reading of the unclear "
                        "responses")
    s.add_argument("--skip-review", action="store_true",
                   help="leave unreadable responses out of every rate instead "
                        "of reviewing them")
    s.set_defaults(func=cmd_score)

    d = sub.add_parser(
        "demo",
        help="score a bundled worked example \u2014 see a real scorecard, no setup",
    )
    d.add_argument("--out", type=Path, default=Path("scorecard.html"),
                   help="where the scorecard goes (default: scorecard.html)")
    d.set_defaults(func=cmd_demo)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    if args.command == "generate" and not (args.schema or args.warehouse):
        print("error: give --schema or --warehouse", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
