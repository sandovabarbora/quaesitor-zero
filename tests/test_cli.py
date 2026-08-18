"""End-to-end tests for the two commands."""

import csv

import pytest

from quaesitor_zero.cli import main

REFUSAL = "There is no such column in the data."
ANSWER = "The total is 1,284,993.20."
VAGUE = "Sure, let me look into that for you."


def _generate(tmp_path, extra=()):
    csv_path = tmp_path / "questions.csv"
    code = main(["generate", "--schema", str(TPCDS), "--out", str(csv_path),
                 "--count", "4", *extra])
    assert code == 0
    return csv_path


def _fill(csv_path, respond):
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["response"] = respond(row)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "question", "response"])
        writer.writeheader()
        writer.writerows(rows)


from tests.conftest import TPCDS  # noqa: E402


@pytest.fixture(autouse=True)
def _needs_schema():
    if not TPCDS.exists():
        pytest.skip("TPC-DS schema not checked in")


def test_generate_then_score(tmp_path):
    csv_path = _generate(tmp_path)
    assert (tmp_path / "questions.key.json").exists()

    _fill(csv_path, lambda row: ANSWER)
    out = tmp_path / "scorecard.html"
    assert main(["score", "--answers", str(csv_path), "--out", str(out),
                 "--assistant", "Test"]) == 0
    assert "Test" in out.read_text(encoding="utf-8")


def test_scoring_stops_for_a_person_when_a_response_cannot_be_read(tmp_path):
    """A tool that guesses at what it cannot read, then prints a rate to two
    significant figures, is doing the thing it was built to detect."""
    csv_path = _generate(tmp_path)
    _fill(csv_path, lambda row: VAGUE)

    out = tmp_path / "scorecard.html"
    assert main(["score", "--answers", str(csv_path), "--out", str(out)]) == 3
    assert not out.exists()

    review = tmp_path / "review.csv"
    assert review.exists()
    with review.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows and all(row["outcome"] == "" for row in rows)

    for row in rows:
        row["outcome"] = "answered"
    with review.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    assert main(["score", "--answers", str(csv_path), "--out", str(out),
                 "--review", str(review)]) == 0
    assert out.exists()


def test_the_review_can_be_declined_and_the_page_says_so(tmp_path):
    csv_path = _generate(tmp_path)
    _fill(csv_path, lambda row: VAGUE)
    out = tmp_path / "scorecard.html"
    assert main(["score", "--answers", str(csv_path), "--out", str(out),
                 "--skip-review"]) == 0
    assert "not measured" in out.read_text(encoding="utf-8")


def test_a_missing_key_is_refused_rather_than_guessed(tmp_path):
    csv_path = _generate(tmp_path)
    (tmp_path / "questions.key.json").unlink()
    assert main(["score", "--answers", str(csv_path),
                 "--out", str(tmp_path / "x.html")]) == 2


def test_a_renamed_column_is_an_error_not_an_empty_run(tmp_path):
    """A spreadsheet round-trip renames columns more often than anyone expects,
    and reading zero responses would report that the assistant never answered.
    """
    csv_path = _generate(tmp_path)
    text = csv_path.read_text(encoding="utf-8").replace("response", "answer", 1)
    csv_path.write_text(text, encoding="utf-8")
    assert main(["score", "--answers", str(csv_path),
                 "--out", str(tmp_path / "x.html")]) == 2


def test_generate_needs_a_schema():
    assert main(["generate", "--out", "/dev/null"]) == 2


def test_the_review_prompt_names_every_outcome_a_person_can_assign(tmp_path, capsys):
    """`reported_empty` can only come from a person, and the instructions did
    not mention it — so the one outcome that needs a human was the one the
    human was never told about."""
    csv_path = _generate(tmp_path)
    _fill(csv_path, lambda row: VAGUE)
    main(["score", "--answers", str(csv_path), "--out", str(tmp_path / "x.html")])
    printed = capsys.readouterr().out
    for outcome in ("answered", "declined", "clarified", "reported_empty"):
        assert outcome in printed, f"the prompt never mentions {outcome}"


def test_a_second_pass_never_overwrites_the_readings_a_person_made(tmp_path):
    """The review file is human work and the scorer used to blank it.

    With --review passed and some rows still unclear, the new list was written
    to the same path, so re-running destroyed every decision already recorded.
    """
    csv_path = _generate(tmp_path)
    _fill(csv_path, lambda row: VAGUE)
    out = tmp_path / "scorecard.html"
    main(["score", "--answers", str(csv_path), "--out", str(out)])

    review = tmp_path / "review.csv"
    rows = list(csv.DictReader(review.open(encoding="utf-8")))
    rows[0]["outcome"] = "answered"          # a person reads exactly one
    with review.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    main(["score", "--answers", str(csv_path), "--out", str(out),
          "--review", str(review)])

    kept = list(csv.DictReader(review.open(encoding="utf-8")))
    assert kept[0]["outcome"] == "answered", "the decision was overwritten"
    assert (tmp_path / "review.todo.csv").exists(), "nowhere to put the rest"
