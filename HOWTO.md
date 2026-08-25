# Running it on your own assistant

The other documents here describe what this tool is. This one is the procedure:
what you type, what comes back, and the two places people get stuck.

Twenty minutes, most of it spent pasting. Nothing is sent anywhere.

---

## Before you start

You need three things.

- **Your schema, as DDL.** A file of `CREATE TABLE` statements. Recipes below.
- **Access to the assistant you want to measure**, in whatever form you already
  use it. The web UI is fine. No API key, no credentials, no connection.
- **Optionally, read-only access to the warehouse itself.** Without it,
  families 4 and 8 emit nothing and family 2 falls back to a guess about how
  far your data goes. The tool says so rather than pretending.

### Getting the DDL out

| Database | How |
|---|---|
| PostgreSQL | `pg_dump --schema-only --no-owner --no-privileges DBNAME > schema.sql` |
| MySQL / MariaDB | `mysqldump --no-data DBNAME > schema.sql` |
| Snowflake | `SELECT GET_DDL('SCHEMA', 'MY_DB.MY_SCHEMA');` |
| BigQuery | `SELECT ddl FROM MY_DATASET.INFORMATION_SCHEMA.TABLES;` |
| Databricks | `SHOW CREATE TABLE catalog.schema.table;` per table |
| DuckDB | point `--warehouse` at the file and skip the DDL entirely |

It does not have to be complete or pretty. Statements the parser cannot read
are listed on stderr and skipped, so you can see what it missed rather than
wonder.

---

## Step 1 — see what a scorecard looks like

Before running anything on your own data:

```bash
uvx quaesitor-zero demo
```

That scores a worked example bundled in the package — a real run against the
public TPC-DS schema — and writes `scorecard.html`. No setup, no files of your
own. If the output is not something you would want, stop here and you have
lost two minutes.

---

## Step 2 — generate the questions

```bash
uvx quaesitor-zero generate --schema schema.sql --out questions.csv
```

```
5 unanswerable questions and 5 matched controls
  family 1: 2
  family 2: 2
  family 6: 1
  (nothing from structurally absent value: needs a read-only connection; none was given)
  (nothing from ambiguous by construction: off by default; enable it explicitly)
  (nothing from missing grain: every table is reachable from the fact table, so no breakdown is missing a join path)

questions: questions.csv
key:       questions.key.json  — keep this, the scorer needs it, and it is deliberately not in the CSV
```

Two things to read in that output.

**The families that produced nothing, and why.** Each line says what it would
have needed. That is not an error; it is the tool declining to invent a
question it cannot warrant.

**The key file.** `questions.key.json` records which questions are unanswerable
and the specific reason. Keep it — `score` needs it — and keep it away from the
assistant. It is one copy-paste from the model's context, and an assistant told
which questions are traps scores well for a reason that has nothing to do with
the system you are measuring.

`questions.csv` has three columns: `id`, `question`, `response`. The third is
empty and is yours to fill.

---

## Step 3 — ask your assistant

There is no `run` command. You do this part, and that is deliberate: it needs
no credentials and no security review, and the person running it reads every
answer, which is where the finding actually lands.

- Ask them **one at a time**, in a fresh conversation each time if you can.
  Twenty questions pasted at once gives the model the set, and a model that
  sees five impossible questions in a row starts declining on pattern rather
  than on the data.
- Paste the response **verbatim** into the `response` column. Do not summarise
  it. "It declined" is your reading; the scorer wants the text.
- If the assistant asks a clarifying question rather than answering, that is a
  real outcome and there is a category for it. Paste that too.
- Leave a row blank if you skipped it. Blank rows are excluded from every rate
  and counted on the scorecard, rather than silently treated as a refusal.

Spreadsheets are fine for this. If you round-trip through Excel, keep the
`id` and `response` column names — the scorer checks for them and stops with a
readable error rather than reporting that your assistant answered nothing.

---

## Step 4 — score it

```bash
uvx quaesitor-zero score --answers questions.csv --out scorecard.html
```

### If it stops and asks you to read something

This is the step people are surprised by, so it is worth stating plainly: **it
is not an error.**

```
1 responses carry evidence of more than one thing and need a person to read them.

  1. open review.csv
  2. put `answered`, `declined`, `clarified` or `reported_empty` in the `outcome` column
  3. re-run with --review review.csv
```

The command exits with status **3** and writes no scorecard.

A response like *"I can't calculate that, as there is no emissions attribute.
The closest figure I can give you is the total item count, which is 18,000"*
carries evidence of declining **and** evidence of producing a figure. No rule
can decide which it was. A tool whose whole claim is that confident output
should not be trusted without a signal is not going to guess and then print a
rate to two significant figures.

So it hands those rows to you. The four outcomes:

| Put this | When |
|---|---|
| `answered` | it gave a figure and presented it as the answer |
| `declined` | it said it could not answer |
| `clarified` | it asked what you meant instead of answering |
| `reported_empty` | it gave the figure **and** said the figure is not an answer |

That last one is why a person is needed. It is the difference between an
assistant that returned zero and an assistant that returned zero and told you
zero means "no rows", and no rule can read that reliably.

Then:

```bash
uvx quaesitor-zero score --answers questions.csv --out scorecard.html --review review.csv
```

If you would rather not read them, `--skip-review` leaves those rows out of
every rate, and the scorecard says how many were excluded. That is an honest
option; a rate computed over responses nobody could read is not.

---

## Step 5 — read the scorecard

```
silent overreach 3/10   over-refusal 2/10
balanced accuracy 75%   coverage 55%
```

**Silent overreach** is the number that matters: questions with no answer in
your data that the assistant answered anyway. Each of those ran, looked like
every other answer, and carried nothing to mark it as unsupported.

**Over-refusal** is the other half, and it is why the tool is not simply a
refusal counter. An assistant that declines everything scores zero overreach
and is useless. The pair is the finding; neither number means much alone.

The scorecard is one self-contained HTML file — every question, every response,
the rule that fired on each, Wilson intervals, and a fingerprint of the run.
Mail it, attach it to a ticket, put it in a board pack. It fetches nothing when
opened.

It also states its own boundary, which is the honest part:

> This measures whether the system declines what it cannot answer. It says
> nothing about whether the answers it does give are numerically correct.

---

## If a question looks wrong

A generated question that is actually answerable makes a correct answer look
like overreach, and it looks exactly like a real finding. Every question
carries its warrant — the specific reason the schema cannot support it — in
`questions.key.json`. Check it against your own knowledge of the data.

If the warrant is wrong, that is a bug and the most useful thing you can report.
[FAMILIES.md](FAMILIES.md) says how each family decides and where each one can
be wrong.

---

## Common problems

**`no key file at questions.key.json`** — `score` looks for the key beside the
answers file. If you moved or renamed either, pass `--key`.

**`needs an id and a response column`** — a spreadsheet renamed them. The error
prints what it actually found.

**`N ids in the answers file are not in the key`** — usually two runs mixed
together. Those rows are ignored and named.

**Everything scores as over-refusal** — check you pasted responses rather than
the questions, and that the assistant had the schema in front of it. It cannot
answer questions about tables it has never been shown.
