"""Churn-risk analytics functions for RevenueIQ.

These functions are the "approved tools" the Claude-powered analyst
layer (Phase 4) will call. They query pre-built SQL views rather than
running ad-hoc SQL, so every number returned here is traceable back to
a reviewed, version-controlled query in sql/views.sql — not something
generated on the fly by an LLM.
"""

import pandas as pd
from sqlalchemy.engine import Engine


def get_customer_churn_risk(engine: Engine) -> pd.DataFrame:
    """Active / At Risk / Churned classification for every household,
    based on how their current recency compares to their own historical
    purchase cadence (not a single global days-since-last-purchase cutoff).

    See the comment above customer_churn_risk in sql/views.sql for the
    exact cadence calculation, population-median fallback for
    single-purchase households (flagged via cadence_is_estimated), and
    the 1.5x/3x thresholds used to assign churn_status. This is a
    retrospective flag as of the dataset's truncated end date, not a
    real-time signal — see the caveat in the view comment.

    Returns a DataFrame with one row per household.
    """
    query = "SELECT * FROM customer_churn_risk ORDER BY household_key"
    return pd.read_sql(query, engine)


def get_churn_summary(engine: Engine) -> pd.DataFrame:
    """Household count, average revenue, and average recency per churn
    status (Active / At Risk / Churned).

    A rollup of get_customer_churn_risk() — the more useful "tool" for
    answering questions about overall customer-base health, since it
    doesn't require scanning all households individually.
    """
    query = """
        SELECT
            churn_status,
            COUNT(*)                       AS household_count,
            ROUND(AVG(total_revenue), 2)   AS avg_revenue,
            ROUND(AVG(order_count), 2)     AS avg_order_count,
            ROUND(AVG(recency_days), 1)    AS avg_recency_days,
            SUM(CASE WHEN cadence_is_estimated THEN 1 ELSE 0 END) AS estimated_cadence_count
        FROM customer_churn_risk
        GROUP BY churn_status
        ORDER BY FIELD(churn_status, 'Active', 'At Risk', 'Churned')
    """
    return pd.read_sql(query, engine)


if __name__ == "__main__":
    # Quick manual check: run this file directly to print the churn
    # summary to the console.
    from src.ingestion.db import get_engine

    engine = get_engine()
    print(get_churn_summary(engine).to_string(index=False))
