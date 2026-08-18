# Contributing

## The most useful thing anyone can do

Tell us a generated question is wrong.

A question that is actually answerable makes a correct answer look like
overreach, and on the scorecard it looks exactly like a real finding. That is
this tool's own silent failure, and there is no defence against it except that
every question prints its warrant — the specific reason the schema cannot
support it — and that being told about a bad one is treated as the point rather
than as a complaint.

Open an issue with the schema (or the part of it that matters), the question,
and why it is answerable. It will be fixed in public.

## Adding a family

`FAMILIES.md` first, then the generator. The document is the specification; if
the code and the document disagree, the document is right and the code has a
bug.

A family needs:

- a **warrant** that is decidable from the schema, or from the schema plus a
  profile. If judging it needs a business definition, it belongs to the layer
  above and not here.
- a **matched control** built from the same tables and the same template. A
  family that emits unanswerable questions without controls measures a
  disposition to refuse, not discrimination.
- a sentence for `_why_empty`, so a schema it has nothing to say about produces
  a reason rather than a silence.

## Rules for the classifier

New rules go in `classify.py` with a name that will be printed next to the
classification. Do not add a rule that resolves the deliberately unresolved
case: a response that both declines and produces a figure goes to a person, and
that is not a gap to be closed with a cleverer regex.

**No model may grade a response.** The whole argument of this tool is that
confident model output should not be trusted without a signal, and a scorecard
whose central number came from a model's judgement would refute itself.

## Tests

```bash
make test
```

The suite runs against the real TPC-DS schema rather than a toy, because every
defect this generator has shipped was found by running it against a real schema
and reading the questions.

Two tests encode the design and should not be relaxed:

- `test_an_assistant_that_refuses_everything_does_not_score_well`
- `test_the_csv_does_not_say_which_questions_are_traps`
