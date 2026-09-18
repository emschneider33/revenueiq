# RevenueIQ

An AI revenue analyst built on the Dunnhumby "Complete Journey" grocery
transaction dataset. Connects real transaction data to an analytics engine,
then uses Claude as a tool-calling interpretation layer on top of validated,
pre-computed metrics — not a chatbot that generates numbers from thin air.

## Architecture

```
Dunnhumby CSVs
      |
Python / pandas ETL
      |
    MySQL
   /      \
Analytics   AI tools
(SQL/Py)    (Claude API)
   \        /
   RevenueIQ (Streamlit)
```

**Core principle:** Claude never invents metrics. All numbers come from
validated SQL/Python functions in `src/analytics/`. Claude's job is to
select the right analytical tool and explain the result in plain English —
never to freehand SQL or make up figures.

## Status

Phase 1: Data foundation — complete. Full ETL pipeline loads all 7 core
Dunnhumby CSVs into a 9-table MySQL schema (~2.6M transaction lines).

Phase 2: Analytics engine — complete. `monthly_revenue`,
`customer_metrics`, `monthly_cohort_retention`, `customer_rfm_segments`,
`product_performance`, and `department_performance` are all built and
validated (see Known data caveats and Performance notes below).

Phase 3: Intelligence layer — started. `monthly_revenue_decomposition`
(revenue bridge: New/Retained/Reactivated customer revenue per month)
is built and validated. Anomaly detection, churn, and promotion
effectiveness are still to come.

## Project structure

```
revenueiq/
├── data/
│   └── raw/          # Original Dunnhumby CSVs — never modified
├── notebooks/         # Exploratory analysis
├── src/
│   ├── ingestion/     # ETL: CSV -> MySQL
│   ├── analytics/     # Revenue, customer, product metric functions
│   └── ai/            # Claude tool-calling layer
├── sql/                # Schema, views, analytical queries
├── app/                # Streamlit UI
├── tests/
├── .env                # Local secrets (git-ignored)
└── environment.yml     # Conda environment
```

## Setup

```bash
conda env create -f environment.yml
conda activate revenueiq
cp .env.example .env   # fill in your MySQL credentials
```

Create the database in MySQL Workbench:

```sql
CREATE DATABASE revenueiq;
```

**Check `innodb_buffer_pool_size` before doing anything else.** Some
local MySQL installs (this one included) end up with this set far
below MySQL's normal 128MB default — as low as 8MB, which is nowhere
near enough to work with a 2.6M-row fact table. With it set that low,
even simple aggregate queries can take minutes or drop the connection
entirely ("Error Code: 2013. Lost connection to MySQL server during
query" is the telltale symptom). To check and fix:

```sql
SHOW VARIABLES LIKE 'innodb_buffer_pool_size';
```

If it's small, edit `innodb_buffer_pool_size` in `my.ini` (Windows:
`C:\ProgramData\MySQL\MySQL Server 8.0\my.ini`, requires editing as
Administrator) to something like `512M`, then restart the MySQL
service for it to take effect. See Performance notes below for more.

## Dataset

[Dunnhumby - The Complete Journey](https://www.kaggle.com/datasets/frtgnn/dunnhumby-the-complete-journey)
— ~2.6M transaction-line records across 2,500 households over 2 years,
plus product, campaign, coupon, and demographic data.

Place the downloaded CSVs in `data/raw/` (untouched, as-downloaded).

## Known data caveats

- **Dates are synthetic.** The raw data has no real calendar dates, only
  a relative `DAY` integer (1 to ~719). `dim_date` anchors day_number=1
  to 2016-01-01 (an arbitrary but documented choice) so real
  month/week/year rollups are possible. The anchor date itself carries
  no business meaning.
- **January 2016 and December 2017 are partial periods**, not genuine
  low-revenue months. The customer panel appears to have ramped up
  gradually in Jan–Mar 2016 (unique customers climb from 540 to 1,592
  over those three months), and the dataset's data collection window
  ends partway through December 2017 (~4,400 transactions vs. a normal
  month's ~12,500–13,600). Any MoM/YoY comparison logic should exclude
  or flag these two months rather than treating them as real declines.
- **The observation window ends just 11 days into December 2017**
  (last transaction day_number=711 → 2017-12-11), not at month's end.
  This compounds the point above for any per-customer recency metric
  (see `customer_metrics`): a household that last shopped in, say,
  November will show a similar recency_days value whether it has truly
  gone quiet or would simply have returned during the rest of a
  December the dataset never captured. Don't set churn/inactivity
  thresholds off `recency_days` without accounting for this truncated
  window. This same compression shows up in `customer_rfm_segments`:
  a large share of households cluster at low recency_days simply
  because the dataset stopped recording, which pulls the R-score
  quintile boundaries tighter than they'd be with a real "today."
- **The same truncation right-censors cohort retention.** In
  `monthly_cohort_retention`, a household acquired late in the
  dataset's life (e.g. Oct 2017) cannot show up at a high
  period_number, because there simply isn't a 2018 in the data. A
  retention curve that appears to "stop" for a recent cohort ran out
  of calendar, not customers — don't compare cohorts past the point
  where the older one is right-censored.
- **Only ~801 of 2,500 households have demographic data** (`dim_household_demographics`).
  Demographic-based segmentation will only ever cover a subset of the
  full customer base.
- **`causal_data.csv` (promotional display/mailer data, ~679MB) is not
  yet loaded** — deferred to when promotion-effectiveness analysis is
  built.
- **No returns in the raw data (checked).** `fact_transaction_line`
  has no negative `quantity` or `sales_value` rows (verified via
  `MIN()` on both columns), so `total_revenue` and `units_sold` in
  `product_performance` / `department_performance` are gross figures,
  not net of returns. Worth re-checking if the ETL or source data ever
  changes.

## Performance notes

- **Check `innodb_buffer_pool_size` first if anything here feels
  slow.** This was the root cause of a full afternoon of "lost
  connection" errors that looked like server crashes but weren't — see
  Setup above. Confirm it's a reasonable size (hundreds of MB, not
  single-digit MB) before assuming a view itself is the problem.
- **`customer_metrics`, `monthly_cohort_retention`, and
  `customer_rfm_segments` re-aggregate the full fact table on every
  query.** Each uses a `GROUP BY` inside a CTE, and MySQL can't push a
  `WHERE` filter through that kind of view — even a single-household
  lookup first computes the aggregate for all ~2,500 households across
  all ~2.6M transaction lines, then filters afterward.
- **`GROUP BY` on text columns is much more expensive than on an
  integer key.** `product_performance` originally grouped by five
  columns including three VARCHAR fields, which made a simple
  `COUNT(*)` take 5+ minutes even with a healthy buffer pool. Grouping
  by `product_id` alone (dim_product's primary key — every other
  selected column is functionally dependent on it) fixed this; keep
  this in mind when adding new views that join in descriptive text
  columns.
- **If using MySQL Workbench, raise the default query timeout.**
  Workbench's default "DBMS connection read timeout" is 30 seconds
  (Edit → Preferences → SQL Editor), which is shorter than a cold-cache
  query against these views can take even with a healthy buffer pool.
  Hitting that limit surfaces as `Error Code: 2013. Lost connection to
  MySQL server during query` — which looks like a server crash but
  isn't one. Raise it to something like 300 seconds.

## Analytics reference

| View/function | File | Purpose |
|---|---|---|
| `monthly_revenue` | `sql/views.sql`, `src/analytics/revenue.py` | Revenue, transaction count, unique customers, AOV by calendar month |
| `customer_metrics` | `sql/views.sql`, `src/analytics/customers.py` | Per-household total revenue, order count, AOV, recency, and tenure (recency/tenure measured relative to the dataset's own last transaction day — see caveat above) |
| `monthly_cohort_retention` | `sql/views.sql`, `src/analytics/retention.py` | Cohort retention curve: share of each acquisition-month cohort still active in each subsequent calendar month (see caveats above on the panel ramp-up, truncated Dec 2017, and right-censoring) |
| `customer_rfm_segments` | `sql/views.sql`, `src/analytics/segmentation.py` | RFM (Recency/Frequency/Monetary) score and segment label per household — Champions, Loyal Customers, Promising, At Risk, Hibernating, Needs Attention |
| `product_performance` | `sql/views.sql`, `src/analytics/products.py` | Per-product revenue, units sold, transaction count, unique customers, avg unit price, with department/brand/commodity descriptors |
| `department_performance` | `sql/views.sql`, `src/analytics/products.py` | Revenue/units/customer-reach rollup by department, with each department's share of total revenue |
| `monthly_revenue_decomposition` | `sql/views.sql`, `src/analytics/revenue.py` | Revenue bridge: each month's total revenue split into New/Retained/Reactivated customer revenue, plus non-returning-customer revenue as context for the following month (see comment in `sql/views.sql` for the exact classification rules and sanity checks) |

## Roadmap

1. **Data foundation** — ETL, MySQL schema ✅
2. **Analytics engine** — revenue, retention, segmentation, product performance ✅
3. **Intelligence layer** — decomposition ✅, anomaly detection, churn, promotion effectiveness
4. **Claude-powered analyst** — tool-calling over validated analytics functions
5. **Streamlit UI**
