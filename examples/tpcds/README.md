# A worked example on TPC-DS

Everything here reproduces in one command, with no warehouse of your own and no
model access:

```bash
make example        # from the repository root
```

## What is in here

| File | What it is |
|---|---|
| `schema.sql` | the TPC-DS schema, 24 tables, exactly as DuckDB's `tpcds` extension creates it |
| `questions.csv` | what `generate` produced from that schema — the file that goes near the assistant |
| `questions.key.json` | which of them are unanswerable, why, and the digests |
| `answers.csv` | a real assistant's responses, verbatim |
| `answers.provenance.json` | which model, which CLI version, and the exact prompt it was given |
| `ask.py` | the harness that produced `answers.csv` |
| `scorecard.html` | the output |

## Why TPC-DS

Because nobody here wrote it. It is a published standard, its schema is not
chosen to make anything look bad, and anyone can regenerate it:

```sql
INSTALL tpcds; LOAD tpcds; CALL dsdgen(sf=0.01);
```

It is also a hard case for this tool in a useful way. TPC-DS **declares no
foreign keys at all**, so the join graph has to be inferred from column naming
before families 3 and 5 can say anything, and its facts carry surrogate date
keys rather than DATE columns, so family 2 has to reach through `date_dim` to
find out when the data ends. Both of those started as bugs that this example
found.

## The result

| | |
|---|---:|
| silent overreach | **3 / 10** |
| reported the emptiness | 1 / 10 |
| over-refusal | 2 / 10 |
| balanced accuracy | 75% |
| coverage | 55% |
| sent to human review | 1 of 20 |

The assistant ran a query of its own on 16 of the 20 questions. Four of the ten
questions with no answer got one anyway.

The one response that went to human review is the interesting one, and it is
recorded in `review.csv` rather than resolved by rule: asked for a total in a
quarter past the end of every sales fact, the assistant led with a bold
**$0.00** and then said, in the same breath, that all three sums came back NULL
— that the join found no rows, rather than that costs were zero.

It was scored **`reported_empty`**, which is the correct action for a question
of that kind: the query runs, it returns something, and the something is not an
answer. Saying so is better than declining. No rule can assign that outcome: telling
a figure that was passed on from one that was explained away needs a reading of
what the number refers to, so it is the one classification only a person makes. A reader who disagrees can change one cell in `review.csv` and re-score.

It was scored as overreach in an earlier pass, before the third mode existed.
The number in this README moved from 4 of 10 to 3 of 10 as a result, which is
worth knowing about a page that asks to be trusted with figures.

## What was measured, and what was not

The assistant was a frontier model given the complete schema, the question, and
a read-only DuckDB it could query through the harness: ask for SQL, run it, hand
back the rows, ask for the answer. That is the minimal shape of the products
being measured. `ask.py` records both prompt templates, so the setup is
inspectable rather than described.

**The first attempt at this example was thrown away, and why is worth keeping.**
It handed the model the schema and nothing else. The model then declined every
question — including the answerable controls — on the grounds that it had no
database connection, which is a refusal for a reason that has nothing to do with
answerability. The run scored perfect restraint and zero usefulness, and
measured the harness rather than the assistant. An instrument for discrimination
needs a system that can actually answer, or one half of the 2×2 is empty by
construction.

The harness also runs the assistant with its own tools disabled. One answer in
an intermediate run was "please approve the pending duckdb tool call" — the CLI
had reached for a shell of its own, and the system being measured was no longer
the one described here.

Three families are silent here and the scorecard says so:

- **3 and 5** need a schema with something genuinely unreachable in it; TPC-DS,
  once its keys are inferred, is a single connected component
- **8** needs a low-cardinality column that reads as a country or region
- **4** found only a calendar artefact worth nothing (`d_dow` is 0 for every
  Sunday) and, correctly, declined to ask about it

That is the honest outcome rather than a gap: a family that found nothing and a
family that never ran look identical in a total, and the scorecard separates
them.

## Running it against your own schema

```bash
quaesitor-zero generate --schema your_schema.sql --out questions.csv
```

Read `questions.csv` before you ask anything. Every question carries a warrant
in the key file — the specific reason the schema cannot support it — and a
question whose warrant is wrong will score a correct answer as a failure.
