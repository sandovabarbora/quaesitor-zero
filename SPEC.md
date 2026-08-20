# quaesitor-zero — product spec

*The free, self-serve layer. Answers one question: does your assistant say "I don't know" when it cannot know?*

---

## 1. Why this one first

It is the only measurement in the four-layer model that **needs nothing from the customer except their schema**. No metric definitions, no interviews, no access to their data, no ground-truth negotiation — because for a structurally unanswerable question the correct answer is always *"I can't answer that"*, and that is knowable from the schema alone.

That property is what makes it a product rather than an engagement:

- runs on their infrastructure, on their keys, with no data reaching you
- no procurement, because nothing is signed and nothing is paid
- no security review, because you never connect to anything
- produces a number about **them** in under an hour, which is what cold email could never do

---

## 2. The design mistake to avoid, and the fix

**A tool that only measures refusals is broken.** A model that refuses everything scores perfectly. Any metric built on refusal rate alone rewards uselessness.

So the instrument must be a **discrimination test**, not a refusal test. Every run mixes two question classes and scores the 2×2:

|  | Assistant answered | Assistant declined |
|---|---|---|
| **Unanswerable** (correct action: decline) | **silent overreach** — the failure of interest | correct refusal |
| **Answerable** (correct action: answer) | correct answer | over-refusal — the friction failure |

The headline number is not a rate but a pair, and the summary statistic is balanced accuracy over the discrimination task. This is a selective-prediction confusion matrix and it should be reported in that literature's vocabulary — coverage, and risk at coverage.

> **Design consequence:** the answerable controls are not optional padding. They are what makes the unanswerable result mean anything. Ship them or the tool is a toy.

---

## 3. What counts as structurally unanswerable

Eight families, all derivable from a schema plus light profiling. Each one is a *class* of generator, not a hardcoded question.

| # | Family | Derived from | Example shape |
|---|---|---|---|
| 1 | **Absent attribute** | column list | asks for an attribute no table carries |
| 2 | **Out-of-range period** | min/max of date columns | asks about a quarter after the data ends |
| 3 | **Missing grain** | FK graph | asks for a breakdown by a dimension with no join path |
| 4 | **Structurally absent value** | data profile: a column null or zero for an entire subpopulation | the cash-tips case: the value cannot exist for that segment |
| 5 | **Unjoinable relation** | connected components of the FK graph | asks to relate two tables in different components |
| 6 | **Unmeasurable metric** | absence of a required table | asks for churn with no cancellation or subscription table |
| 7 | **Ambiguous by construction** | several plausible columns for one business word | four columns could be "revenue"; correct action is to ask which, not to pick |
| 8 | **Absent population** | distinct values of a filter column | filters to a country or segment not present in the data |

Families 4 and 8 need a data profile rather than DDL alone, so they are optional in the DDL-only mode (§5) and enabled when a read-only connection is available.

**Family 7 deserves its own note.** It is the only one where declining is not quite the right answer — asking a clarifying question is. Score it as a third outcome (*clarified*) and treat clarification as correct. This is the family most likely to appear in a real production system and the one a semantic layer is supposed to solve, which makes it the most interesting to measure and the most likely to convert a reader into a customer.

> **TODO (yours, not mine):** decide whether family 7 belongs in the free tier. It is the strongest result and it is also the closest to layer I. There is a defensible argument for holding it back.

---

## 4. Answerable controls

For each unanswerable question the generator emits a **matched** answerable one — same tables, same shape, same difficulty, differing only in that it can be answered. Matching matters: if the controls are trivially easy, over-refusal looks impossibly rare and the discrimination number is inflated.

Suggested default: **10 unanswerable, 10 matched controls, 3 repeats** = 60 assistant interactions. That is a lunch break for whoever runs it, which is the adoption ceiling to design for.

---

## 5. How it reaches their assistant — the decision that determines adoption

There is no common API across Genie, Cortex Analyst, Spotter, Looker Conversational Analytics and homegrown assistants, and building adapters for each is a trap: it is unbounded work, it breaks constantly, and every adapter needs credentials you do not want to touch.

**Ship a CSV round-trip as v1.**

```
quaesitor-zero generate --schema schema.sql --out questions.csv
#  ... they ask their assistant the 20 questions, any way they like,
#      and paste each response into the answers column ...
quaesitor-zero score --answers answers.csv --out scorecard.html
```

Why this is the right call and not a compromise:

- works with an assistant that has **only a UI**, which is most of them
- zero credentials, zero integration, zero security conversation
- the person running it **reads every answer**, so the failures land on them personally rather than arriving as a summary statistic — which is the entire conversion mechanism
- you cannot be accused of touching anything

Add an optional `--adapter` hook later for teams who want it in CI, and let the community write adapters. Do not write them first.

**Classification of a response as answered / declined / clarified** must be mechanical and inspectable, not an LLM judgement — the whole thesis of the surrounding work is that a model should not be the arbiter. Suggested: a small rule set over the response text plus a required human confirmation pass in the scorer for anything ambiguous, with the ambiguous count reported. **Do not use an LLM to grade this.** It would be self-refuting.

---

## 6. Output

One self-contained HTML scorecard, generated the same way as the sample report, carrying:

- the 2×2, with Wilson score intervals
- balanced accuracy, coverage, and risk at coverage
- every question with its response and its classification, so the reader can disagree
- **a run fingerprint** — schema digest, question-set digest, generator version, timestamp, counts, and the assistant name as free text
- a one-paragraph reading of what the numbers mean, generated from the numbers rather than written by hand

And the boundary, stated on the scorecard itself, in the same register as `LIMITS.md`:

> This measures whether the system declines what it cannot answer. It says nothing about whether the answers it does give are numerically correct — that requires the definitions your business owns, and it is not derivable from a schema.

That sentence is both honest and the entire upsell, which is why it should be phrased carefully and never as a pitch.

---

## 7. Packaging

| Decision | Recommendation | Why |
|---|---|---|
| Name | `quaesitor-zero` | says it is the free floor of something larger without saying "free trial" |
| Licence | Apache-2.0 | permissive enough for corporate legal to wave through without a review; MIT also fine, GPL would block adoption in exactly your target companies |
| Distribution | PyPI + GitHub, `uv`/`pipx` runnable | you are already on `uv` and `pyproject.toml` |
| Dependencies | DuckDB, stdlib, one HTML template. No LLM SDK in the core | the core must run with no model access at all, or it cannot be audited by the people you are asking to trust it |
| Repo contents | generator, scorer, families as documented rules, the eight-family reference doc, and a worked example on TPC-DS | the TPC-DS example lets anyone reproduce a full run in one command with no warehouse of their own |

The README's first screen must contain the number, not the pitch. Something in the shape of: *on a public standard schema, a frontier model answered N of 10 questions it could not possibly have answered.* Then the install line. Nothing else above the fold.

---

## 8. What this is not, so scope stays closed

- not a correctness test — that is layers I–III and it needs their definitions
- not an eval platform — no experiment tracking, no dashboards, no accounts
- not a hosted service — nothing to host is the feature
- not an adapter zoo — CSV first, community adapters later
- no telemetry of any kind, ever, including "anonymous usage statistics". Your landing page promises this and the tool must keep the same promise or the promise is worth nothing

---

## 9. The demand test this doubles as

Pre-committed criteria, decided now rather than after seeing the result:

| Signal | Threshold, 3 weeks from launch | Reading |
|---|---|---|
| installs / clones | ≥ 30 | somebody is curious |
| scorecards sent to you unprompted | ≥ 2 | somebody is worried, which is the buying emotion |
| an inbound asking about layers I–III | ≥ 1 | the ladder works |

**If installs are under 5 and nobody writes:** the pain is not felt yet. The correct response is not to try harder at outreach. It is to keep publishing measurements, keep the tool alive, and stop spending evenings on sales until the market catches up.

That is a real possible outcome and deciding it in advance is what stops it turning into nine months of low-grade disappointment.

---

## 10. Build order

1. The eight families as a written reference doc — before any code. It is the intellectual content and it is also a publishable artifact on its own.
2. Generator for families 1, 2, 3, 5, 6 (DDL only, no profiling needed).
3. Matched control generator.
4. Scorer, 2×2, Wilson intervals, HTML scorecard with fingerprint.
5. TPC-DS worked example, checked in, reproducible in one command.
6. Families 4 and 8 behind an optional read-only connection.
7. Family 7 if you decide it belongs here.
8. Adapter hook, last, and only if somebody asks.

Steps 1–5 are the product. Everything after is response to demand that may not arrive.
