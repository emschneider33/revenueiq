"""Revenue analytics functions for RevenueIQ.

These functions are the "approved tools" the Claude-powered analyst
layer (Phase 4) will call. They query pre-built SQL views rather than
running ad-hoc SQL, so every number returned here is traceable back to
a reviewed, version-controlled query in sql/views.sql — not something
generated on the fly by an LLM.
"""

import pandas as pd
from sqlalchemy.engine import Engine


def get_monthly_revenue(engine: Engine) -> pd.DataFrame:
    """Total revenue, transaction count, unique customers, and AOV by month.

    Returns a DataFrame with one row per calendar month, sorted chronologically.
    """
    query = "SELECT * FROM monthly_revenue ORDER BY year_num, month_num"
    return pd.read_sql(query, engine)


if __name__ == "__main__":
    # Quick manual check: run this file directly to print the monthly
    # revenue table to the console.
    from src.ingestion.db import get_engine

    engine = get_engine()
    df = get_monthly_revenue(engine)
    print(df.to_string(index=False))
