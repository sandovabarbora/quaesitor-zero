# quaesitor-zero against six DuckDB warehouses

*18 August 2026. Generation only — no model was asked anything for this table.*

Every warehouse in `quaesitor-method/data/` produced a full set of 10
unanswerable questions and 10 matched controls. What differs is **which
families had anything to say**, and that turns out to be a property of the
warehouse worth reading on its own.

| Warehouse | 1 absent attr | 2 out-of-range | 3 missing grain | 4 absent value | 5 unjoinable | 6 unmeasurable | 7 ambiguous | 8 absent pop | families |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| retail (synthetic) | 3 | 1 | · | · | 3 | 2 | · | 1 | 5 |
| saas (synthetic) | 1 | 3 | · | · | 2 | 2 | 1 | 1 | **6** |
| tpcds | 3 | 3 | · | · | · | 2 | 2 | · | 4 |
| taxi (real, 2.9M rows) | 2 | 2 | 2 | 1 | 1 | 1 | 1 | · | **7** |
| medallion (CRM+ERP raw) | 2 | · | · | · | 5 | · | · | · | **2** |
| injected | 3 | 1 | · | · | 3 | 2 | · | 1 | 5 |

## What the shape of that table says

**The dirtier the warehouse, the more the tool has to say — except at the
extremes.** Taxi, the only large real-data warehouse, supports seven of eight
families. TPC-DS, a clean and fully connected star schema, supports four.

**Medallion supports two, and the reason is a finding rather than a gap.** Its
six tables carry **no typed date column at all** — `cst_create_date` and
`BDATE` are text. Family 2 needs a date it can take a maximum of, so it is
silent, and families 6 and 8 find nothing because the raw extracts do not
name the events or carry clean categorical values. A bronze layer that stores
every date as a string is exactly the layer where an assistant will be asked
questions about time, and the tool cannot construct one. Worth stating in
`LIMITS.md` for the free tier: **quaesitor-zero needs typed dates**, and the
absence of them is itself something a customer should hear.

**Families 3 and 5 are complementary, and both are about the join graph.**
Nothing in the middle: a warehouse either has unreachable tables (medallion,
5 questions) or does not (tpcds, 0). Family 3 fired only on taxi.

## Family 4 rediscovered the cash-tip case unaided

The single most compelling example in the whole method — a mean over a segment
where the value is not collected — was found by the generator from the data
alone, with no hand-written question:

> **What is the average tip amount where payment type is 2?**
>
> `trips.tip_amount` is null or zero for 99.97% of the 439,191 rows where
> `trips.payment_type` is 2 (128 exceptions), so the value is not collected for
> that segment rather than merely missing. Averaging the rows that do exist
> answers a different question.

That is the free tier producing, from a schema and a profile, the finding the
paid method produces from weeks of definition work. It is the best single
argument the tool has, and it should be the example on the landing page.

## Six defects these six warehouses found

Every one of them would have produced a wrong number that looked exactly like a
right one. None were found by reasoning about the code.

1. **DuckDB's own catalogue views** were read as customer tables, so the
   generator wrote a question about breaking down `pg_class`.
2. **`ss_ticket_number` was treated as a measure**, producing "what was the
   total order number in Q3 2031" — a trick question, not a measurement.
3. **A calendar dimension is not coverage.** TPC-DS ships a `date_dim`
   spanning 1900–2100 while its sales cover about five years, so the
   out-of-range period was being taken from the calendar and asked about 2101.
4. **SCD validity dates were read as event dates.** A question constrained by
   `item.i_rec_start_date` carried a warrant that was simply false.
5. **"Last year" is not a well-defined period.** On TPC-DS it resolves through
   `MAX(d_year) - 1` to 2099, a sentinel row, so the query comes back empty and
   a careful assistant refuses. It refused three matched controls in one real
   run for exactly that reason, and every one was scored as over-refusal —
   the assistant was right and the question was wrong.
6. **Family 4 demanded absolute emptiness.** Real data is 99.97%, not 100%, so
   the detector found nothing in any of six warehouses, including the case it
   exists for.

The fifth is the one worth keeping in mind for the paid method too: a control
question that is wrong scores a correct answer as a failure, and it looks
identical to a real finding.
