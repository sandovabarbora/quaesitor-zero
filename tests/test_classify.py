"""Tests for reading a response mechanically."""

import pytest

from quaesitor_zero.classify import (
    ANSWERED, CLARIFIED, DECLINED, MISSING, UNCLEAR, apply_review, classify,
)


@pytest.mark.parametrize("text", [
    "There is no column for household income in the schema.",
    "I can't answer that — the data does not contain marital status.",
    "The warehouse doesn't record carbon footprint anywhere.",
    "That period is outside the range of available data.",
    "I don't have any data on employee headcount.",
    "There's no join path between support tickets and sales.",
])
def test_a_refusal_is_read_as_one(text):
    assert classify("Q1", text).outcome == DECLINED


@pytest.mark.parametrize("text", [
    "Total revenue was 1,284,993.20 for the period.",
    "The total is 42 orders.",
    "| region | revenue |\n| north | 1200 |",
])
def test_an_answer_is_read_as_one(text):
    assert classify("Q1", text).outcome == ANSWERED


def test_a_query_alone_is_not_an_answer():
    """A text-to-SQL assistant emits SQL for everything, refusals included.

    "I can't run this, but here is the query I would run" is a refusal that
    happens to contain a SELECT. Reading the query as an answer sent three
    quarters of one real run to human review.
    """
    query = "SELECT SUM(ss_net_paid) FROM store_sales WHERE d_year = 2001"
    assert classify("Q1", query).outcome == UNCLEAR
    assert classify("Q1", f"There is no such column. {query}").outcome == DECLINED


def test_a_clarifying_question_is_its_own_outcome():
    """Family 7's correct action is to ask, not to decline."""
    result = classify("Q1", "There are four columns that could mean revenue. "
                            "Which one do you want me to use?")
    assert result.outcome == CLARIFIED


def test_a_response_that_declines_and_also_gives_a_figure_goes_to_a_person():
    """The interesting case, and the one a rule cannot settle.

    "There's no household income column, but average order value is 1,234" is a
    correct refusal. "Cash tips average 0.00, note that cash tips aren't
    recorded" is an overreach that then confesses. Telling those apart needs a
    reading of what the number refers to.
    """
    result = classify("Q1", "There is no such column, but here is 1,234.00 "
                            "for the closest thing.")
    assert result.outcome == UNCLEAR
    assert result.needs_review


def test_an_empty_response_is_missing_rather_than_a_refusal():
    """Counting a blank cell as a refusal makes a broken export look careful."""
    assert classify("Q1", "").outcome == MISSING
    assert classify("Q1", "   ").outcome == MISSING


def test_nothing_matched_is_unclear_rather_than_a_guess():
    assert classify("Q1", "Sure, let me look into that for you.").outcome == UNCLEAR


def test_every_classification_shows_the_rule_that_fired():
    """A total whose evidence is not shown is a claim."""
    result = classify("Q1", "There is no column for that.")
    assert result.decline_hits
    assert "declines:" in result.evidence


def test_review_replaces_only_what_the_rules_could_not_read():
    """Quietly overriding a mechanical classification makes the scorecard an
    opinion rather than a measurement."""
    rules = {
        "Q1": classify("Q1", "Sure, let me look into that."),
        "Q2": classify("Q2", "There is no such column."),
    }
    assert apply_review(rules, {"Q1": "answered"})["Q1"].outcome == ANSWERED

    with pytest.raises(ValueError, match="not.*unclear|classified"):
        apply_review(rules, {"Q2": "answered"})
    with pytest.raises(ValueError, match="not one of"):
        apply_review(rules, {"Q1": "probably fine"})


@pytest.mark.parametrize("text", [
    "This isn't something I can calculate from our warehouse.",
    "There's no way to compute that from these tables.",
])
def test_a_refusal_phrased_at_a_distance_is_still_a_refusal(text):
    """The earlier rules all wanted the negation next to the verb.

    "This isn't something I can calculate from our warehouse" is as plain a
    refusal as exists and it matched nothing, so a correct refusal went to
    human review.
    """
    assert classify("Q1", text).outcome == DECLINED


# --- reported_empty -----------------------------------------------------

def test_reported_empty_is_never_produced_by_a_rule():
    """Only a person may assign it.

    Telling a correct mode-C answer apart from an overreach that hedges needs
    a reading of what the number refers to. A rule that guessed would be the
    instrument doing the thing the instrument exists to warn about.
    """
    from quaesitor_zero.classify import REPORTED_EMPTY, classify
    responses = [
        "$0.00 - but all three sums came back NULL, so there is no data for "
        "that quarter rather than zero cost.",
        "The average is 0.00. Tips are not recorded for cash payments.",
        "Revenue was 47.1M.",
        "There is no such column in the schema.",
    ]
    assert all(classify("Q", r).outcome != REPORTED_EMPTY for r in responses)


def test_the_real_tpcds_response_goes_to_review():
    """Verbatim from examples/tpcds, the case that motivated the outcome."""
    from quaesitor_zero.classify import UNCLEAR, classify
    response = (
        "**$0.00** - but that number is almost certainly a data artifact, not "
        "a real answer.\n\nAll three component sums (store, catalog, web) came "
        "back as NULL, meaning the join found *zero* matching rows for Q3 2003 "
        "across every sales table - not that costs summed to zero.\n\nI'd flag "
        'this to your colleague as "no data found for Q3 2003" rather than '
        '"$0 cost."'
    )
    assert classify("F2-02U", response).outcome == UNCLEAR


def test_a_person_may_record_reported_empty():
    from quaesitor_zero.classify import (
        REPORTED_EMPTY, UNCLEAR, Classification, apply_review,
    )
    before = {"F2-02U": Classification("F2-02U", UNCLEAR, reason="both")}
    after = apply_review(before, {"F2-02U": "reported_empty"})
    assert after["F2-02U"].outcome == REPORTED_EMPTY


def test_an_unknown_outcome_is_still_refused():
    import pytest
    from quaesitor_zero.classify import UNCLEAR, Classification, apply_review
    before = {"Q": Classification("Q", UNCLEAR, reason="both")}
    with pytest.raises(ValueError, match="is not one of"):
        apply_review(before, {"Q": "sort of"})
