"""RevenueIQ analytics — promotion effectiveness (display/mailer lift).

Thin wrappers around sql/views.sql's promotion views
(product_promotion_weekly, promotion_lift_summary,
product_promotion_lift). No calculation happens here -- these
functions just run the reviewed SQL and return a DataFrame, same as
every other module in src/analytics/.
"""

import pandas as pd


def get_promotion_lift_summary(engine) -> pd.DataFrame:
    """Overall sales lift (all products combined) when promoted vs. not."""
    return pd.read_sql("SELECT * FROM promotion_lift_summary", engine)


def get_product_promotion_lift(engine, limit: int = 20) -> pd.DataFrame:
    """Per-product sales lift when promoted vs. not, highest lift first.

    Only includes products with at least 3 promoted and 3
    not-promoted product/store/weeks (filtered in the view itself),
    so the lift % isn't computed off a single noisy data point.
    `limit` caps how many rows come back -- the view is already
    ordered by revenue_lift_pct descending, so this returns the
    biggest promotion responders. Pass a larger limit (or query the
    view directly) to see further down the list.
    """
    limit = int(limit)  # guard against non-integer input before string-formatting into SQL
    return pd.read_sql(f"SELECT * FROM product_promotion_lift LIMIT {limit}", engine)


if __name__ == "__main__":
    # Quick manual check: run this file directly to print the overall
    # promotion lift summary to the console.
    from src.ingestion.db import get_engine

    engine = get_engine()
    print(get_promotion_lift_summary(engine).to_string(index=False))
