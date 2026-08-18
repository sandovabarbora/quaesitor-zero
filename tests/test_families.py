"""Tests for the eight generators.

The contract they all share: a family emits **pairs**, and the two halves are
built from the same tables and the same template. A control that is easier than
its unanswerable twin makes over-refusal look rarer than it is and inflates the
discrimination number.
"""

import random

import pytest

from quaesitor_zero.families import (
    ANSWER, CLARIFY, DECLINE, FAMILIES, REPORT_EMPTY, absent_attribute,
    ambiguous_by_construction, out_of_range_period, unjoinable_relation,
    unmeasurable_metric,
)

# What counts as correct on an unanswerable question depends on why it cannot
# be answered: decline when no query expresses it, ask when several do and they
# disagree, and report the emptiness when a query runs and returns something
# that is not an answer. All three are "did not hand over a number as if it
# were one", which is what this half of the 2x2 measures.
HELD = (DECLINE, CLARIFY, REPORT_EMPTY)


def _run(generator, schema, limit=10, **kwargs):
    return generator(schema, random.Random(0), limit, **kwargs)


@pytest.mark.parametrize("family", FAMILIES, ids=[f.key for f in FAMILIES])
def test_every_pair_is_matched(family, tpcds):
    """Both halves name the same tables and expect opposite actions."""
    for unanswerable, answerable in _run(family.generator, tpcds):
        assert unanswerable.kind == "unanswerable"
        assert answerable.kind == "answerable"
        assert answerable.expected == ANSWER
        assert unanswerable.expected in HELD
        assert unanswerable.tables == answerable.tables
        assert unanswerable.twin == answerable.id
        assert answerable.twin == unanswerable.id


@pytest.mark.parametrize("family", FAMILIES, ids=[f.key for f in FAMILIES])
def test_every_question_carries_a_warrant(family, tpcds):
    """A question with no stated reason cannot be disagreed with."""
    for question in [q for pair in _run(family.generator, tpcds) for q in pair]:
        assert question.warrant.strip()
        assert question.text.strip().endswith(("?", "."))


def test_controls_are_distinct(tpcds):
    """Five identical controls is a measurement of one wording.

    Family 7 fell back to a single shared control and emitted the same question
    five times; the over-refusal rate it produced was really n=1.
    """
    for family in FAMILIES:
        pairs = _run(family.generator, tpcds)
        controls = [a.text for _u, a in pairs]
        assert len(set(controls)) == len(controls), f"{family.key} repeats a control"


def test_no_question_is_asked_twice_across_a_family(tpcds):
    for family in FAMILIES:
        texts = [q.text for pair in _run(family.generator, tpcds) for q in pair]
        assert len(set(texts)) == len(texts), f"{family.key} repeats a question"


def test_ambiguity_expects_a_question_rather_than_a_refusal(tpcds):
    """Family 7 is the one family where declining is not the right action."""
    pairs = _run(ambiguous_by_construction, tpcds)
    assert pairs
    assert all(u.expected == CLARIFY for u, _a in pairs)


def test_out_of_range_period_follows_a_surrogate_date_key(tpcds):
    """TPC-DS facts carry `ss_sold_date_sk`, not a DATE column.

    Looking only at the fact's own columns made family 2 silent on a warehouse
    whose entire purpose is time series.
    """
    pairs = _run(out_of_range_period, tpcds)
    assert pairs, "family 2 found no date to constrain a measure by"


def test_unjoinable_says_nothing_when_everything_joins(tpcds):
    """A family with nothing to say must say nothing, not guess."""
    assert _run(unjoinable_relation, tpcds) == []


def test_unjoinable_fires_on_a_genuinely_split_graph(toy):
    pairs = _run(unjoinable_relation, toy)
    assert pairs
    tables = {t for u, _a in pairs for t in u.tables}
    assert "support_ticket" in tables


def test_a_metric_is_not_measurable_because_of_a_coincidental_token(tpcds):
    """`ship_mode.sm_contract` is a shipping contract, not a subscription.

    Matching every metric term against every column name read churn as
    measurable on a schema that records no subscription of any kind.
    """
    asked = {u.text for u, _a in _run(unmeasurable_metric, tpcds)}
    assert any("churn" in text for text in asked)


def test_absent_attribute_asks_the_right_table(tpcds):
    """Shipping weight is a property of an item, not of a customer."""
    for unanswerable, _a in _run(absent_attribute, tpcds):
        if "weight" in unanswerable.text or "warranty" in unanswerable.text:
            assert unanswerable.tables == ("item",)
        if "promoter" in unanswerable.text or "language" in unanswerable.text:
            assert unanswerable.tables == ("customer",)


def test_an_absent_attribute_is_really_absent(tpcds):
    """The warrant is the whole claim, so it has to hold."""
    vocabulary = tpcds.vocabulary
    for unanswerable, _a in _run(absent_attribute, tpcds):
        terms = unanswerable.warrant.split("matches any of ")[1].rstrip(".")
        terms = {t.strip() for t in terms.split(",") if t.strip()}
        assert not (terms & vocabulary), f"{unanswerable.text}: {terms & vocabulary}"


def test_generation_is_deterministic(tpcds):
    first = [q.text for pair in absent_attribute(tpcds, random.Random(7), 10) for q in pair]
    second = [q.text for pair in absent_attribute(tpcds, random.Random(7), 10) for q in pair]
    assert first == second
