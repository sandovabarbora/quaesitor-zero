"""Assemble a question set from a schema and write it out.

Two files are written, and the split is deliberate:

    questions.csv        id, question, response — the file that goes near the
                         assistant, carrying nothing that gives the game away
    questions.key.json   which questions are unanswerable, why, and the digests

Putting `expected: decline` in the same row as the question would be one
copy-paste away from the assistant's context, and an assistant told which
questions are traps scores well for a reason that has nothing to do with the
system being measured. The key file is what the scorer reads.

References:
    - csv module: https://docs.python.org/3/library/csv.html
"""

import csv
import hashlib
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from quaesitor_zero import __version__
from quaesitor_zero.families import FAMILIES, Family, Pair, Question
from quaesitor_zero.schema import Schema

logger = logging.getLogger(__name__)

CSV_FIELDS = ("id", "question", "response")


@dataclass
class QuestionSet:
    """A generated set, with the account of how it came out that way."""

    questions: List[Question]
    schema_digest: str
    per_family: Dict[int, int] = field(default_factory=dict)
    empty_families: Dict[str, str] = field(default_factory=dict)
    assumptions: List[str] = field(default_factory=list)
    generated_at: str = ""
    schema_source: str = ""

    @property
    def unanswerable(self) -> List[Question]:
        return [q for q in self.questions if q.kind == "unanswerable"]

    @property
    def answerable(self) -> List[Question]:
        return [q for q in self.questions if q.kind == "answerable"]

    def digest(self) -> str:
        """Fingerprint of the questions themselves, in a stable order."""
        blob = json.dumps(
            sorted((q.id, q.text, q.expected) for q in self.questions),
            ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]

    def key(self) -> dict:
        return {
            "generator_version": __version__,
            "generated_at": self.generated_at,
            "schema_source": self.schema_source,
            "schema_digest": self.schema_digest,
            "question_digest": self.digest(),
            "counts": {
                "unanswerable": len(self.unanswerable),
                "answerable": len(self.answerable),
                "per_family": {str(k): v for k, v in sorted(self.per_family.items())},
            },
            "assumptions": self.assumptions,
            "families_with_nothing_to_say": self.empty_families,
            "questions": [
                {
                    "id": q.id,
                    "family": q.family,
                    "family_name": q.family_name,
                    "kind": q.kind,
                    "expected": q.expected,
                    "text": q.text,
                    "warrant": q.warrant,
                    "twin": q.twin,
                    "tables": list(q.tables),
                }
                for q in self.questions
            ],
        }


def generate(schema: Schema, count: int = 10, seed: Optional[int] = None,
             include: Sequence[str] = (), exclude: Sequence[str] = (),
             horizon_years: int = 5) -> QuestionSet:
    """Build a question set from a schema.

    Args:
        schema: The loaded schema, profiled or not.
        count: How many unanswerable questions to aim for. Each one is paired
            with a matched answerable control, so the run is twice this.
        seed: Random seed. Defaults to the schema digest, so the same schema
            produces the same questions without anybody passing anything.
        include: Family keys to switch on beyond the defaults.
        exclude: Family keys to switch off.
        horizon_years: How far past the run date family 2 goes when there is no
            profile to say where the data ends.

    Returns:
        The set, with per-family counts and a note for every family that had
        nothing to say.

    Note:
        Families are drawn round-robin rather than in order. Taking family 1
        until the quota is full would produce ten questions about absent
        attributes and call it a survey of eight families.
    """
    digest = schema.digest()
    rng = random.Random(seed if seed is not None else int(digest, 16))

    chosen: List[Family] = []
    empty: Dict[str, str] = {}
    for family in FAMILIES:
        if family.key in exclude:
            empty[family.name] = "switched off for this run"
            continue
        if not family.default_on and family.key not in include:
            empty[family.name] = "off by default; enable it explicitly"
            continue
        if family.needs_profile and not schema.profile.present:
            empty[family.name] = "needs a read-only connection; none was given"
            continue
        chosen.append(family)

    produced: Dict[int, List[Pair]] = {}
    for family in chosen:
        kwargs = {"horizon_years": horizon_years} if family.number == 2 else {}
        pairs = family.generator(schema, rng, count, **kwargs)
        if pairs:
            produced[family.number] = pairs
        else:
            empty[family.name] = _why_empty(family, schema)

    # Round-robin across the families that produced anything.
    taken: List[Pair] = []
    order = sorted(produced)
    depth = 0
    while len(taken) < count and order:
        for number in list(order):
            if depth >= len(produced[number]):
                order.remove(number)
                continue
            taken.append(produced[number][depth])
            if len(taken) == count:
                break
        depth += 1

    questions: List[Question] = [q for pair in taken for q in pair]
    # Interleave, so the file does not read as a block of traps followed by a
    # block of controls. Whoever pastes twenty questions into an assistant sees
    # the order, and an order that telegraphs the design changes how they ask.
    rng.shuffle(questions)

    per_family: Dict[int, int] = {}
    for unanswerable, _ in taken:
        per_family[unanswerable.family] = per_family.get(unanswerable.family, 0) + 1

    assumptions = []
    if not schema.profile.present:
        assumptions.append(
            f"No data was read. Family 2 assumes the data does not reach "
            f"{horizon_years} years past the run date, which is weaker than "
            f"reading the actual maximum date."
        )
    if any(fk.inferred for fk in schema.foreign_keys):
        inferred = sum(1 for fk in schema.foreign_keys if fk.inferred)
        assumptions.append(
            f"{inferred} join edges were inferred from column naming rather "
            f"than declared. Families 3 and 5 rest on them."
        )
    if schema.skipped:
        assumptions.append(
            f"{len(schema.skipped)} DDL statements did not load and their "
            f"tables are absent from every question."
        )

    if len(taken) < count:
        logger.warning("Asked for %d unanswerable questions, the schema "
                       "supported %d", count, len(taken))

    return QuestionSet(
        questions=questions,
        schema_digest=digest,
        per_family=per_family,
        empty_families=empty,
        assumptions=assumptions,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_source=schema.source,
    )


def _why_empty(family: Family, schema: Schema) -> str:
    """Say why a family produced nothing, in terms of this schema.

    A family that found nothing and a family that was never run look identical
    in a total. They are not the same thing, and the difference is usually the
    most useful sentence on the scorecard.
    """
    if family.number == 1:
        return "every candidate attribute is already carried by some column"
    if family.number == 2:
        return "no table carries both a measure and a date column"
    if family.number == 3:
        return ("every table is reachable from the fact table, so no "
                "breakdown is missing a join path")
    if family.number == 4:
        return "no measure is empty across a whole segment"
    if family.number == 5:
        return "the join graph is a single component; every table connects"
    if family.number == 6:
        return "the schema mentions every metric's required events"
    if family.number == 7:
        return "no business term matches three or more distinct columns"
    if family.number == 8:
        return "no low-cardinality column looks like a country or region"
    return "nothing to say about this schema"


def write(question_set: QuestionSet, csv_path: Path,
          key_path: Optional[Path] = None) -> Path:
    """Write the question CSV and its key.

    Args:
        question_set: The generated set.
        csv_path: Where the CSV goes.
        key_path: Where the key goes; defaults to the CSV's name with
            `.key.json`.

    Returns:
        The key path, so callers can tell the operator to keep it.
    """
    key_path = key_path or csv_path.with_suffix(".key.json")
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for question in question_set.questions:
            writer.writerow({"id": question.id, "question": question.text,
                             "response": ""})

    key_path.write_text(
        json.dumps(question_set.key(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote %d questions to %s and the key to %s",
                len(question_set.questions), csv_path, key_path)
    return key_path


def read_key(path: Path) -> dict:
    """Load a key file written by `write`."""
    return json.loads(path.read_text(encoding="utf-8"))
