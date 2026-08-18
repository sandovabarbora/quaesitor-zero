"""Tests for the scorecard.

Self-contained is a promise the page makes to whoever opens it, and it is the
kind of promise that breaks quietly: one stylesheet link, one web font, one
tracking pixel, and a document that says it sends nothing anywhere does.
"""

import re

import pytest

from quaesitor_zero.classify import classify_all
from quaesitor_zero.generate import generate
from quaesitor_zero.report import BOUNDARY, render
from quaesitor_zero.score import score

ANSWER = "The total is 1,284,993.20."


@pytest.fixture
def scorecard(tpcds):
    question_set = generate(tpcds, count=6)
    key = question_set.key()
    responses = {q["id"]: ANSWER for q in key["questions"]}
    scores = score(key["questions"], responses, classify_all(responses))
    return render(scores, key, "Example Assistant"), scores, key


def test_the_page_requests_nothing_from_anywhere(scorecard):
    html, _scores, _key = scorecard
    for pattern in (r"https?://[^\s\"'<]+", r"<script", r"<link", r"@import",
                    r"url\(\s*['\"]?https?:"):
        found = re.findall(pattern, html, re.IGNORECASE)
        # quaesitor.eu may be named in prose, but never fetched from.
        assert not [f for f in found if "quaesitor.eu" not in f], f"{pattern}: {found}"


def test_every_question_and_response_is_printed(scorecard):
    html, _scores, key = scorecard
    for question in key["questions"]:
        assert question["id"] in html
        assert question["warrant"][:40] in html


def test_the_fingerprint_is_on_the_page(scorecard):
    html, _scores, key = scorecard
    assert key["schema_digest"] in html
    assert key["question_digest"] in html
    assert "Example Assistant" in html


def test_the_boundary_is_stated_on_the_scorecard_itself(scorecard):
    """It is both the honest part and the entire upsell, so it is not optional
    and it is not phrased as a pitch."""
    html, _scores, _key = scorecard
    assert BOUNDARY in html
    assert "numerically correct" in html


def test_responses_are_escaped(tpcds):
    """A response is arbitrary text from another system."""
    question_set = generate(tpcds, count=2)
    key = question_set.key()
    hostile = "<script>alert('x')</script>"
    responses = {q["id"]: hostile for q in key["questions"]}
    scores = score(key["questions"], responses, classify_all(responses))
    html = render(scores, key, "x")
    assert hostile not in html
    assert "&lt;script&gt;" in html


def test_a_family_that_said_nothing_is_named_on_the_page(scorecard):
    html, _scores, _key = scorecard
    assert "nothing to say" in html.lower()
