"""Retention analytics functions for RevenueIQ.

These functions are the "approved tools" the Claude-powered analyst
layer (Phase 4) will call. They query pre-built SQL views rather than
running ad-hoc SQL, so every number returned here is traceable back to
a reviewed, version-controlled query in sql/views.sql — not something
generated on the fly by an LLM.
"""

import pandas as pd
from sqlalchemy.engine import Engine


def get_monthly_cohort_retention(engine: Engine) -> pd.DataFrame:
    """Cohort retention curve: for each acquisition-month cohort, the
    share of that cohort active (>=1 transaction) in each subsequent
    calendar month.

    "Active" means at least one transaction that month — this is
    retail/repeat-purchase retention, not subscription retention.
    period_number=0 is the cohort's own acquisition month, where
    retention_rate is always 1.0 by definition. See the comment above
    monthly_cohort_retention in sql/views.sql for important caveats
    around the Jan-Mar 2016 panel ramp-up, the truncated Dec 2017
    window, and right-censoring near the end of the dataset.

    Returns a DataFrame with one row per (cohort_year, cohort_month,
    period_number).
    """
    query = """
        SELECT * FROM monthly_cohort_retention
        ORDER BY cohort_year, cohort_month, period_number
    """
    return pd.read_sql(query, engine)


if __name__ == "__main__":
    # Quick manual check: run this file directly to print the cohort
    # retention table to the console.
    from src.ingestion.db import get_engine

    engine = get_engine()
    df = get_monthly_cohort_retention(engine)
    print(df.to_string(index=False))
