"""Tests for assembling and writing a question set."""

import csv
import json

from quaesitor_zero.generate import generate, read_key, write


def test_the_csv_does_not_say_which_questions_are_traps(tpcds, tmp_path):
    """The CSV goes near the assistant; the key does not.

    `expected: decline` in the same row as the question is one copy-paste from
    the assistant's context, and an assistant told which questions are traps
    scores well for a reason that has nothing to do with the system.
    """
    question_set = generate(tpcds, count=6)
    csv_path = tmp_path / "questions.csv"
    write(question_set, csv_path)

    with csv_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["id", "question", "response"]
        rows = list(reader)

    blob = csv_path.read_text(encoding="utf-8").lower()
    for tell in ("unanswerable", "answerable", "decline", "clarify", "warrant",
                 "family", "trap"):
        assert tell not in blob, f"the CSV gives away {tell!r}"
    assert all(row["response"] == "" for row in rows)


def test_the_key_carries_everything_the_scorer_needs(tpcds, tmp_path):
    question_set = generate(tpcds, count=6)
    key_path = write(question_set, tmp_path / "questions.csv")
    key = read_key(key_path)

    assert key["schema_digest"] and key["question_digest"]
    assert key["counts"]["unanswerable"] == 6
    assert key["counts"]["answerable"] == 6
    assert {q["id"] for q in key["questions"]} == {q.id for q in question_set.questions}


def test_every_unanswerable_question_has_its_control(tpcds):
    """The pair is the unit. A run missing controls measures a disposition."""
    question_set = generate(tpcds, count=8)
    ids = {q.id for q in question_set.questions}
    for question in question_set.questions:
        assert question.twin in ids


def test_families_are_drawn_round_robin(tpcds):
    """Taking family 1 until the quota is full produces ten questions about
    absent attributes and calls it a survey of eight families."""
    question_set = generate(tpcds, count=8, include=["ambiguous_by_construction"])
    assert len(question_set.per_family) >= 3
    assert max(question_set.per_family.values()) <= 4


def test_a_family_with_nothing_to_say_says_why(tpcds):
    """A family that found nothing and a family that never ran look identical
    in a total, and they are not the same thing."""
    question_set = generate(tpcds, count=6)
    assert "unjoinable relation" in question_set.empty_families
    assert "component" in question_set.empty_families["unjoinable relation"]
    assert "connection" in question_set.empty_families["structurally absent value"]


def test_ambiguity_is_off_unless_asked_for(tpcds):
    default = generate(tpcds, count=10)
    assert not any(q.family == 7 for q in default.questions)
    assert "ambiguous by construction" in default.empty_families

    enabled = generate(tpcds, count=10, include=["ambiguous_by_construction"])
    assert any(q.family == 7 for q in enabled.questions)


def test_the_same_schema_gives_the_same_questions(tpcds):
    """Seeded from the schema digest, so a reader can regenerate the set and
    check that the questions on the scorecard are the ones the schema implies.
    """
    assert generate(tpcds, count=8).digest() == generate(tpcds, count=8).digest()


def test_an_assumption_the_run_made_is_written_down(tpcds):
    """Family 2 without a profile guesses where the data ends."""
    question_set = generate(tpcds, count=8)
    assert any("years past the run date" in a for a in question_set.assumptions)
    assert any("inferred" in a for a in question_set.assumptions)
