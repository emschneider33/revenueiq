"""Product performance analytics functions for RevenueIQ.

These functions are the "approved tools" the Claude-powered analyst
layer (Phase 4) will call. They query pre-built SQL views rather than
running ad-hoc SQL, so every number returned here is traceable back to
a reviewed, version-controlled query in sql/views.sql — not something
generated on the fly by an LLM.
"""

import pandas as pd
from sqlalchemy.engine import Engine


def get_product_performance(engine: Engine) -> pd.DataFrame:
    """Per-product revenue, units sold, transaction count, unique
    customers, and average unit price, with department/brand/commodity
    descriptors from dim_product.

    Only products that appear in at least one transaction are included.
    This can be a large result set (tens of thousands of products) —
    prefer get_top_products() or filtering by department for most uses.
    """
    query = "SELECT * FROM product_performance ORDER BY total_revenue DESC"
    return pd.read_sql(query, engine)


def get_top_products(engine: Engine, n: int = 10) -> pd.DataFrame:
    """The N highest-revenue products.

    Thin convenience wrapper around product_performance — the natural
    "approved tool" for a "what are our best-selling products" question,
    rather than asking the Claude layer to write its own LIMIT/ORDER BY.
    """
    n = int(n)  # guard against non-integer input before string-formatting into SQL
    query = f"SELECT * FROM product_performance ORDER BY total_revenue DESC LIMIT {n}"
    return pd.read_sql(query, engine)


def get_department_performance(engine: Engine) -> pd.DataFrame:
    """Revenue, units, and customer-reach rollup by department, with
    each department's share of total revenue.

    Returns a DataFrame with one row per department, sorted by revenue
    descending.
    """
    query = "SELECT * FROM department_performance ORDER BY total_revenue DESC"
    return pd.read_sql(query, engine)


if __name__ == "__main__":
    # Quick manual check: run this file directly to print the
    # department-level rollup to the console.
    from src.ingestion.db import get_engine

    engine = get_engine()
    print(get_department_performance(engine).to_string(index=False))
