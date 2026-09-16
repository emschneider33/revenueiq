"""Customer segmentation analytics functions for RevenueIQ.

These functions are the "approved tools" the Claude-powered analyst
layer (Phase 4) will call. They query pre-built SQL views rather than
running ad-hoc SQL, so every number returned here is traceable back to
a reviewed, version-controlled query in sql/views.sql — not something
generated on the fly by an LLM.
"""

import pandas as pd
from sqlalchemy.engine import Engine


def get_customer_rfm_segments(engine: Engine) -> pd.DataFrame:
    """RFM (Recency, Frequency, Monetary) score and segment label for
    every household.

    Scores are quintiles (1-5, 5=best) relative to this dataset's own
    households, not an absolute benchmark. See the comment above
    customer_rfm_segments in sql/views.sql for the exact scoring and
    segment-label logic, and for caveats inherited from customer_metrics
    (recency measured against the dataset's truncated end date).

    Returns a DataFrame with one row per household.
    """
    query = "SELECT * FROM customer_rfm_segments ORDER BY household_key"
    return pd.read_sql(query, engine)


def get_segment_summary(engine: Engine) -> pd.DataFrame:
    """Household count and average revenue/orders/recency per RFM segment.

    A rollup of get_customer_rfm_segments() — the more useful "tool" for
    answering questions about overall customer-base health, since it
    doesn't require scanning all ~2,500 households individually.
    """
    query = """
        SELECT
            rfm_segment,
            COUNT(*)                       AS household_count,
            ROUND(AVG(total_revenue), 2)   AS avg_revenue,
            ROUND(AVG(order_count), 2)     AS avg_order_count,
            ROUND(AVG(recency_days), 1)    AS avg_recency_days
        FROM customer_rfm_segments
        GROUP BY rfm_segment
        ORDER BY avg_revenue DESC
    """
    return pd.read_sql(query, engine)


if __name__ == "__main__":
    # Quick manual check: run this file directly to print the segment
    # summary to the console.
    from src.ingestion.db import get_engine

    engine = get_engine()
    print(get_segment_summary(engine).to_string(index=False))
