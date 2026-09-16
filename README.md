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

Phase 1: Data foundation — in progress.

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

## Roadmap

1. **Data foundation** — ETL, MySQL schema (current)
2. **Analytics engine** — revenue, retention, segmentation, product performance
3. **Intelligence layer** — decomposition, anomaly detection, churn, promotion effectiveness
4. **Claude-powered analyst** — tool-calling over validated analytics functions
5. **Streamlit UI**
