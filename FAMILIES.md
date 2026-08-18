# The eight families of structurally unanswerable question

A question is **structurally unanswerable** when no correct answer exists that
the data could support — not because the answer is hard to compute, but because
the thing being asked about is not in there at all. The correct action is to say
so.

This document is the intellectual content of `quaesitor-zero`. The code
implements it; if the two disagree, this document is right and the code has a
bug.

## Why the distinction has to be structural

"Unanswerable" is a claim, and a claim needs a warrant. Ours is deliberately
narrow: **every family below is decidable from the schema, or from the schema
plus a profile of what is in the columns.** Nobody has to agree with us about
what revenue means, or what counts as an active customer, for the question to be
unanswerable — the attribute is absent, the join does not exist, the period is
outside the data.

That narrowness is the whole reason this can run without an engagement. The
moment a question needs a business definition to be judged, it belongs to
layer I, and it is not in here.

## The failure being measured

An assistant that declines a question it cannot answer has behaved correctly. An
assistant that produces a confident, well-formatted, plausible number for a
question with no answer has failed **silently** — nothing downstream carries a
signal that the number should not be trusted.

The counterpart failure matters too. An assistant that declines everything is
useless and would score perfectly on refusals alone, which is why every
unanswerable question in a run is paired with a matched answerable control, and
why the headline is a discrimination measure rather than a refusal rate. See
§ Matched controls.

---

## 1 · Absent attribute

**Derived from:** the column list.

**Shape:** asks for an attribute that no table in the schema carries.

**Why it is unanswerable:** the attribute is not recorded anywhere. There is no
join, no derivation, and no proxy that produces it, because the fact was never
captured.

**Example:** *"What is the average household income of our customers?"* against
a schema whose customer table records name, address, and signup date.

**How the generator decides:** an attribute term is absent when neither it nor
any of its synonyms appears as a token in any column name or table name in the
schema. The synonym list is part of the generated question set and is written
into the run's fingerprint, so a reader who thinks `income` should have matched
`annual_revenue_band` can see exactly what was compared.

**Known false-positive risk:** a column named opaquely (`attr_17`, `flag_c`)
carries an attribute the name does not reveal. This is why the generated
question set is handed over for review before it is asked, and why the scorecard
prints every question.

---

## 2 · Out-of-range period

**Derived from:** the minimum and maximum of date columns (with a profile), or a
horizon assumption (from DDL alone).

**Shape:** asks about a historical period for which no data exists.

**Why it is unanswerable:** the rows are not there. A model can compute an
answer for the period — it will be zero, or empty, or an extrapolation — but the
question as asked ("what *was* revenue in Q3 2031") has no answer, and returning
zero without saying the period is outside the data is the failure.

**Example:** *"What was total revenue in the third quarter of 2031?"*

**How the generator decides:**

- With a read-only connection, the period is the quarter immediately after
  `max(date)` in the relevant date column. This is the strong form: it is out of
  range by one quarter, not by a decade, so an assistant cannot pass by pattern-
  matching on an implausible-looking year.
- From DDL alone the range is unknown, so the generator uses a period `--horizon`
  years beyond the run date (default 5) and **states the assumption on the
  scorecard**. A warehouse holding data five years into the future is not
  impossible — a forecast table would — so this variant is the weaker one and it
  is labelled as such.

**Boundary:** a question asking for a *forecast* of a future period is not in
this family. It is answerable in principle and belongs to a different argument.
Every generated question in this family is in the past tense about a period the
data does not reach.

---

## 3 · Missing grain

**Derived from:** the foreign-key graph.

**Shape:** asks for a measure broken down by a dimension attribute that has no
join path to the table holding the measure.

**Why it is unanswerable:** the breakdown cannot be produced. Any answer
requires inventing an association between rows that the schema does not record.

**Example:** *"Break down total sales by warehouse region"* where the sales fact
has no key reaching the warehouse dimension.

**How the generator decides:** it computes the undirected reachability closure
of the declared foreign keys, plus inferred keys if `--infer-keys` is on, and
picks a dimension attribute in a table not in the measure table's closure.

**Dependency worth stating plainly:** most analytical warehouses declare no
foreign keys at all. Where none are declared and inference is off, this family
emits nothing rather than guessing, and the scorecard says so. A family that
silently emits zero questions and a family that found nothing to say look
identical in a total, which is why the count is printed per family.

---

## 4 · Structurally absent value

**Derived from:** a data profile — a column that is null, zero, or empty for an
entire subpopulation.

**Shape:** asks for a quantity that cannot exist for the segment being asked
about, and the impossibility is a property of how the data is collected rather
than of this particular extract.

**Why it is unanswerable:** the value is not merely missing, it is
uncollectable. Averaging over the rows that do exist answers a different
question, and doing so without saying so is the failure.

**Example, the canonical one:** *"What is the average tip on cash-paid taxi
trips?"* A cash tip is handed over in the vehicle and the meter never sees it,
so the column is zero for every cash trip. The mean of those zeros is a number,
it is well-formatted, and it is wrong in a way nothing downstream reveals.

**How the generator decides:** for each (categorical column, numeric column)
pair it looks for a category value where the numeric column is null or zero
across 100% of rows, above a minimum row count. It then asks for the numeric
column restricted to that category.

**Requires a connection.** DDL cannot express this, and no amount of naming
convention substitutes for looking.

---

## 5 · Unjoinable relation

**Derived from:** the connected components of the foreign-key graph.

**Shape:** asks to relate two tables that sit in different components.

**Why it is unanswerable:** there is no path. Producing a number requires a
cross join or a fabricated key, and both are wrong in a way that survives review
because the result looks like a normal aggregate.

**Example:** *"How many support tickets were raised by customers who bought
product X?"* where the ticket tables and the sales tables share no key.

**How the generator decides:** it partitions the FK graph into components and
pairs a table from one with a table from another. If the graph has a single
component, this family emits nothing — correctly.

---

## 6 · Unmeasurable metric

**Derived from:** the absence of a table the metric requires.

**Shape:** asks for a standard business metric whose defining event is not
recorded anywhere in the schema.

**Why it is unanswerable:** the metric is not a computation over what is there.
It needs an event the warehouse never captured.

**Examples:**

| Metric | Requires | Unanswerable when |
|---|---|---|
| Churn rate | subscription or cancellation events | no subscription, contract, or cancellation table |
| Refund rate | returns or refunds | no return, refund, or credit-note table |
| Inventory turnover | stock levels | no inventory or stock table |
| Cart abandonment | sessions or cart events | no session, event, or cart table |
| Employee headcount | an employee or HR table | no employee, staff, or payroll table |

**How the generator decides:** each metric template names the table concepts it
requires; the metric is emitted as unanswerable only when no table name or
column name in the schema matches any of them. The matching terms travel with
the question set so the judgement can be checked.

**Boundary:** this is not "the metric is hard to define". A schema with a
subscription table makes churn *definable and arguable*, which is layer I's
problem, and the question is then not in this family.

---

## 7 · Ambiguous by construction

**Derived from:** several plausible columns for one business word.

**Shape:** uses a business term that maps to more than one column in the schema,
with no principled way to choose from the question alone.

**Why declining is not quite right:** unlike every other family, this question
*has* an answer — several, and the assistant cannot know which is meant. The
correct action is therefore to **ask**, not to decline and not to pick.

**Example:** *"What was our revenue last year?"* against a schema carrying
`list_price`, `sales_price`, `ext_sales_price`, and `net_paid` — four defensible
readings of one word, differing by tens of percent.

**Scored as a third outcome.** A response that asks which column or which
definition is meant is scored `clarified` and counted as correct. A response
that silently picks one is the failure, and it is the failure most likely to be
happening in production right now, because picking one is what a helpful
assistant does.

**How the generator decides:** a business term is ambiguous when three or more
distinct columns match its synonym set across the schema. Two is not enough —
two columns are frequently the same thing named twice.

**Off by default.** This family is the closest of the eight to layer I, and
whether it belongs in a free tier is a commercial decision rather than a
technical one. Enable it with `--include-ambiguous`.

---

## 8 · Absent population

**Derived from:** the distinct values of a filter column.

**Shape:** filters to a category value that does not occur in the data.

**Why it is unanswerable:** the population is empty. The honest response is that
the filter matches nothing, and an assistant returning `0` without saying so has
reported an absence as a measurement — the two are not the same, and the
difference is invisible downstream.

**Example:** *"How much did we sell in Portugal last quarter?"* where no row in
any country column is Portugal.

**How the generator decides:** it reads the distinct values of low-cardinality
text columns and picks a plausible sibling value that is absent — a country in
the same region, a segment name in the same style — so that the question does not
look strange to the person asking it.

**Requires a connection**, for the same reason as family 4.

---

## Matched controls

Every unanswerable question is emitted with an **answerable twin**: same tables,
same shape, same syntactic difficulty, differing only in that the answer exists.

| Family | The twin asks for |
|---|---|
| 1 Absent attribute | an attribute the same table does carry |
| 2 Out-of-range period | a period inside the data |
| 3 Missing grain | a breakdown by a dimension that is reachable |
| 4 Structurally absent value | the same measure for a category where it is populated |
| 5 Unjoinable relation | two tables inside one component |
| 6 Unmeasurable metric | a metric whose required tables are present |
| 7 Ambiguous by construction | a business term matching exactly one column |
| 8 Absent population | a category value that does occur |

This is not padding, and it is not a sanity check. Without it the instrument
measures nothing:

- an assistant that declines everything scores 100% on the unanswerable half
- an assistant that answers everything scores 100% on the answerable half
- only the pair separates a system that discriminates from one that has a
  disposition

If the controls are easier than the unanswerable questions, over-refusal looks
rarer than it is and the discrimination number is inflated. Generating the twin
from the same tables and the same template is what keeps them matched, and it is
worth checking by eye in the generated CSV before a run.

---

## What this cannot tell you

The families establish that a question has no answer. They say nothing about
whether the answers an assistant *does* give are numerically right — that needs
the definitions the business owns, an anchor it already trusts, and a person who
owns the metric. It is not derivable from a schema, and it is not in here.
