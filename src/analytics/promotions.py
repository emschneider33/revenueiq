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


def get_product_promotion_lift(engine) -> pd.DataFrame:
    """Per-product sales lift when promoted vs. not.

    Only includes products with at least 3 promoted and 3
    not-promoted product/store/weeks (filtered in the view itself),
    so the lift % isn't computed off a single noisy data point.
    Sorted by revenue_lift_pct descending -- biggest promotion
    responders first.
    """
    return pd.read_sql("SELECT * FROM product_promotion_lift", engine)
