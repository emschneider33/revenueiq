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

Phase 2: Analytics engine — in progress. `monthly_revenue`,
`customer_metrics`, and `monthly_cohort_retention` views/functions built
and validated (see Known data caveats and Performance notes below).

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
  window.
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

## Performance notes

- **`customer_metrics` and `monthly_cohort_retention` re-aggregate the
  entire fact table on every query.** Both use a `GROUP BY` inside a
  CTE, and MySQL can't push a `WHERE` filter through that kind of
  view — even `SELECT ... WHERE household_key = 718` first computes
  the aggregate for all ~2,500 households across all ~2.6M
  transaction lines, then filters afterward. Fine at this data size,
  but worth knowing before assuming a filtered query will be cheap.
- **Expect a slow first query and fast subsequent ones.** A cold
  InnoDB buffer pool means the first query against one of these views
  after a while can take 30-50+ seconds (reading ~2.6M rows off disk);
  once those pages are cached, the same shape of query drops to a few
  seconds. This is normal, not a sign anything is broken.
- **If using MySQL Workbench, raise the default query timeout.**
  Workbench's default "DBMS connection read timeout" is 30 seconds
  (Edit → Preferences → SQL Editor), which is shorter than a cold-cache
  query against these views can take. Hitting that limit surfaces as
  `Error Code: 2013. Lost connection to MySQL server during query` —
  which looks like a server crash but isn't one. Raise it to something
  like 300 seconds.

## Analytics reference

| View/function | File | Purpose |
|---|---|---|
| `monthly_revenue` | `sql/views.sql`, `src/analytics/revenue.py` | Revenue, transaction count, unique customers, AOV by calendar month |
| `customer_metrics` | `sql/views.sql`, `src/analytics/customers.py` | Per-household total revenue, order count, AOV, recency, and tenure (recency/tenure measured relative to the dataset's own last transaction day — see caveat above) |
| `monthly_cohort_retention` | `sql/views.sql`, `src/analytics/retention.py` | Cohort retention curve: share of each acquisition-month cohort still active in each subsequent calendar month (see caveats above on the panel ramp-up, truncated Dec 2017, and right-censoring) |

## Roadmap

1. **Data foundation** — ETL, MySQL schema (current)
2. **Analytics engine** — revenue, retention, segmentation, product performance
3. **Intelligence layer** — decomposition, anomaly detection, churn, promotion effectiveness
4. **Claude-powered analyst** — tool-calling over validated analytics functions
5. **Streamlit UI**
