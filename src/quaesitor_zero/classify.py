"""Decide, mechanically, whether a response answered, declined, or asked.

No model grades this. The whole argument of the surrounding work is that a
confident model output should not be trusted without a signal, so a scorecard
whose central number came from a model's judgement would refute itself.

What this can do instead is be inspectable: every classification carries the
rules that fired, and a response carrying evidence of two different things is
not guessed at — it is marked `unclear` and goes to a human, and the count of
those is printed on the scorecard.

References:
    - re: https://docs.python.org/3/library/re.html
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

ANSWERED = "answered"
DECLINED = "declined"
CLARIFIED = "clarified"
REPORTED_EMPTY = "reported_empty"
UNCLEAR = "unclear"
MISSING = "missing"

OUTCOMES = (ANSWERED, DECLINED, CLARIFIED, REPORTED_EMPTY, UNCLEAR, MISSING)

# REPORTED_EMPTY is never produced by a rule, only by a person in review.
# It is the response that gives a figure and then says the figure is not an
# answer -- "$0.00, but all three sums came back NULL, so there is no data for
# that quarter rather than zero cost". Telling that apart from an overreach
# that happens to hedge needs a reading of what the number refers to, which is
# the judgement a rule cannot make and a model must not be trusted to make in
# an instrument built on the claim that models cannot adjudicate correctness.
# So the rules send it to `unclear`, and this exists so the person reviewing it
# has somewhere true to put it.

# Each rule is (name, pattern). The name is what appears on the scorecard next
# to the classification, so a reader who disagrees can see what was matched
# rather than being asked to trust the total.
DECLINE_RULES: Sequence[Tuple[str, str]] = (
    ("no such column", r"\b(no|not any|isn'?t an?|is no)\b[^.!?]{0,40}\b(column|field|attribute|table)\b"),
    ("not in the data", r"\b(not|isn'?t|aren'?t)\b[^.!?]{0,30}\b(in|available in|present in|captured in|recorded in|stored in)\b[^.!?]{0,20}\b(the )?(data|dataset|database|schema|warehouse|tables?)\b"),
    ("does not contain", r"\b(does|do|did)\s+not\s+(contain|include|have|track|record|store|capture)\b"),
    ("doesn't contain", r"\b(doesn'?t|don'?t|didn'?t)\s+(contain|include|have|track|record|store|capture)\b"),
    ("cannot answer", r"\b(can'?t|cannot|can not|unable to|not able to)\b[^.!?]{0,30}\b(answer|determine|calculate|compute|provide|tell|know|find|retrieve)\b"),
    ("i don't know", r"\bi\s+(don'?t|do not)\s+(know|have)\b"),
    ("there is no", r"\bthere\s+(is|are|was|were)\s+no\b"),
    ("no data for", r"\bno\s+(data|rows|records|information|values)\b"),
    ("outside the range", r"\b(outside|beyond|past|after|before)\b[^.!?]{0,30}\b(range|coverage|period|available data|data ends|latest date)\b"),
    ("no join path", r"\b(no|without a?)\s+(join|relationship|link|foreign key|common key|way to (join|relate|connect))\b"),
    ("not possible", r"\b(not possible|impossible|cannot be (answered|determined|computed))\b"),
    ("would need", r"\bwould (need|require)\b[^.!?]{0,40}\b(table|column|data|field)\b"),
    # "This isn't something I can calculate from our warehouse" is as plain a
    # refusal as there is, and it matched nothing: the earlier rules all want
    # the negation next to the verb, and here it is four words away.
    ("not something I can", r"\b(isn'?t|is not|aren'?t|not)\s+something (i|we) can\b"),
    ("no way to", r"\bno way to\s+(\w+\s+){0,3}(calculate|compute|answer|determine|derive|measure|get)\b"),
    ("needs data we lack", r"\b(needs?|requires?)\b[^.!?]{0,40}\b(clickstream|session|event|log)s?\b[^.!?]{0,40}\b(we|this|the)\b"),
)

CLARIFY_RULES: Sequence[Tuple[str, str]] = (
    ("which one", r"\bwhich\b[^.!?]{0,60}\?"),
    ("do you mean", r"\b(do you mean|did you mean|are you asking|do you want)\b"),
    ("could you clarify", r"\b(could|can|would) you (please )?(clarify|specify|confirm|tell me)\b"),
    ("several possible", r"\b(several|multiple|more than one|two|three|four|a few)\b[^.!?]{0,40}\b(columns?|fields?|definitions?|interpretations?|measures?|ways)\b"),
    ("ambiguous", r"\b(ambiguous|unclear which|depends on (what|which|how) you)\b"),
)

# Producing SQL is **not** evidence of an answer. A text-to-SQL assistant emits
# a query for everything, including the questions it is refusing — "I can't run
# this, but here is the query I would run" is a refusal that happens to contain
# a SELECT. Counting the query as an answer read three quarters of one real run
# as carrying evidence of two things, and sent the operator to review responses
# that were plain refusals.
ANSWER_RULES: Sequence[Tuple[str, str]] = (
    ("figure given", r"(?<![\w.])[€$£]?\s?\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|(?<![\w.])\d+\.\d+|(?<![\w.])\d+\s?%"),
    ("result table", r"\|[^|\n]+\|[^|\n]+\|"),
    ("the total is", r"\b(the (total|answer|result|average|count|figure) (is|was|comes to))\b"),
    ("plain count", r"\bthere (are|were)\s+\d+\b"),
    # A distribution is an answer even when every count is a small integer.
    # "Women (25), Men (22), Electronics (21)..." matched nothing, because the
    # figure rule wants thousands separators or decimals, and a plainly
    # answered control was sent to human review twice.
    ("counts listed", r"(\(\d+\)|—\s*\d+|:\s*\d+)(?:[\s\S]{0,140}?(\(\d+\)|—\s*\d+|:\s*\d+)){3,}"),
)


@dataclass
class Lexicon:
    """The rule sets, so a run in another language can replace them."""

    decline: Sequence[Tuple[str, str]] = field(default_factory=lambda: DECLINE_RULES)
    clarify: Sequence[Tuple[str, str]] = field(default_factory=lambda: CLARIFY_RULES)
    answer: Sequence[Tuple[str, str]] = field(default_factory=lambda: ANSWER_RULES)

    @classmethod
    def load(cls, path: Optional[Path]) -> "Lexicon":
        """Read a lexicon from JSON, falling back to the built-in English one.

        Args:
            path: JSON with `decline`, `clarify` and `answer` objects mapping a
                rule name to a regular expression, or None.

        Returns:
            The lexicon.
        """
        if not path:
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            decline=tuple(raw.get("decline", {}).items()) or DECLINE_RULES,
            clarify=tuple(raw.get("clarify", {}).items()) or CLARIFY_RULES,
            answer=tuple(raw.get("answer", {}).items()) or ANSWER_RULES,
        )

    def digest_source(self) -> str:
        return json.dumps(
            {"decline": dict(self.decline), "clarify": dict(self.clarify),
             "answer": dict(self.answer)},
            sort_keys=True,
        )


@dataclass
class Classification:
    """What one response was read as, and why."""

    question_id: str
    outcome: str
    decline_hits: List[str] = field(default_factory=list)
    clarify_hits: List[str] = field(default_factory=list)
    answer_hits: List[str] = field(default_factory=list)
    reason: str = ""

    @property
    def needs_review(self) -> bool:
        return self.outcome == UNCLEAR

    @property
    def evidence(self) -> str:
        parts = []
        if self.decline_hits:
            parts.append("declines: " + ", ".join(self.decline_hits))
        if self.clarify_hits:
            parts.append("asks: " + ", ".join(self.clarify_hits))
        if self.answer_hits:
            parts.append("answers: " + ", ".join(self.answer_hits))
        return "; ".join(parts) or "no rule matched"


def _hits(text: str, rules: Sequence[Tuple[str, str]]) -> List[str]:
    return [name for name, pattern in rules
            if re.search(pattern, text, re.IGNORECASE)]


def classify(question_id: str, response: str,
             lexicon: Optional[Lexicon] = None) -> Classification:
    """Read one response.

    Args:
        question_id: The question it answers.
        response: What the assistant said, verbatim.
        lexicon: Rule sets; the built-in English ones by default.

    Returns:
        The classification, carrying the rules that fired.

    Note:
        A response that both declines and produces a figure is the interesting
        case — "there's no household income column, but average order value is
        1,234" is a correct refusal, while "cash tips average 0.00, note that
        cash tips aren't recorded" is arguably an overreach that then confesses.
        Telling those apart needs a reading of what the number refers to, which
        is exactly the judgement a rule cannot make and a model must not be
        trusted to make here. Both come out `unclear` and go to a person.
    """
    lexicon = lexicon or Lexicon()
    text = (response or "").strip()
    if not text:
        return Classification(question_id, MISSING, reason="empty response")

    declines = _hits(text, lexicon.decline)
    clarifies = _hits(text, lexicon.clarify)
    answers = _hits(text, lexicon.answer)

    # A question mark alone is not a clarification: assistants restate the
    # question, and a restatement followed by a number is an answer.
    asking = bool(clarifies) and text.rstrip().endswith("?")

    if declines and answers:
        outcome, reason = UNCLEAR, ("declines and produces a figure; a person "
                                    "has to say what the figure refers to")
    elif asking and answers:
        outcome, reason = UNCLEAR, "asks a question and produces a figure"
    elif asking:
        outcome, reason = CLARIFIED, "asks which reading is meant"
    elif declines:
        outcome, reason = DECLINED, "says the data cannot support it"
    elif answers:
        outcome, reason = ANSWERED, "produces a figure or a query"
    elif clarifies:
        outcome, reason = CLARIFIED, "raises the ambiguity without a figure"
    else:
        outcome, reason = UNCLEAR, "no rule matched"

    return Classification(question_id, outcome, declines, clarifies, answers,
                          reason)


def classify_all(responses: Dict[str, str],
                 lexicon: Optional[Lexicon] = None) -> Dict[str, Classification]:
    """Classify a whole answers file.

    Args:
        responses: Question id to response text.
        lexicon: Rule sets.

    Returns:
        Question id to classification.
    """
    lexicon = lexicon or Lexicon()
    return {qid: classify(qid, text, lexicon) for qid, text in responses.items()}


def apply_review(classifications: Dict[str, Classification],
                 decisions: Dict[str, str]) -> Dict[str, Classification]:
    """Overwrite unclear classifications with a person's reading.

    Args:
        classifications: What the rules produced.
        decisions: Question id to one of `answered`, `declined`, `clarified`
            or `reported_empty`.

    Returns:
        The classifications, with reviewed ones replaced.

    Raises:
        ValueError: On an unknown outcome, or a decision about a question that
            was not unclear — quietly overriding a mechanical classification is
            how a scorecard becomes an opinion.
    """
    out = dict(classifications)
    for qid, outcome in decisions.items():
        outcome = outcome.strip().lower()
        if not outcome:
            continue
        if outcome not in (ANSWERED, DECLINED, CLARIFIED, REPORTED_EMPTY):
            raise ValueError(
                f"{qid}: {outcome!r} is not one of {ANSWERED}, {DECLINED}, "
                f"{CLARIFIED}, {REPORTED_EMPTY}"
            )
        if qid not in out:
            raise ValueError(f"{qid} is not in the answers file")
        if not out[qid].needs_review:
            raise ValueError(
                f"{qid} was classified {out[qid].outcome} by rule, not left "
                f"unclear. Review is for the ones the rules could not read."
            )
        out[qid] = Classification(qid, outcome, out[qid].decline_hits,
                                  out[qid].clarify_hits, out[qid].answer_hits,
                                  reason="read by a person")
    return out
