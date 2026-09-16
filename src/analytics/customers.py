"""Customer-level analytics functions for RevenueIQ.

These functions are the "approved tools" the Claude-powered analyst
layer (Phase 4) will call. They query pre-built SQL views rather than
running ad-hoc SQL, so every number returned here is traceable back to
a reviewed, version-controlled query in sql/views.sql — not something
generated on the fly by an LLM.
"""

import pandas as pd
from sqlalchemy.engine import Engine


def get_customer_metrics(engine: Engine) -> pd.DataFrame:
    """Per-household total revenue, order count, AOV, recency, and tenure.

    Recency and tenure are both measured relative to the dataset's own
    last transaction day, not a real calendar date — see the comment
    above customer_metrics in sql/views.sql for why. Returns a DataFrame
    with one row per household that has at least one transaction.
    """
    query = "SELECT * FROM customer_metrics ORDER BY household_key"
    return pd.read_sql(query, engine)


if __name__ == "__main__":
    # Quick manual check: run this file directly to print the customer
    # metrics table to the console.
    from src.ingestion.db import get_engine

    engine = get_engine()
    df = get_customer_metrics(engine)
    print(df.to_string(index=False))
