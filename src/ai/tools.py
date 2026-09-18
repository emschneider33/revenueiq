"""Tool definitions and dispatcher for the RevenueIQ AI analyst (Phase 4).

TOOL_SPECS is the list of tools handed to the Claude API's `tools`
parameter. call_tool() is the only place a tool name gets routed to an
actual Python function -- every one of those functions lives in
src/analytics/ and queries a pre-built, reviewed SQL view. Nothing in
this file computes a number itself.

Scope note: get_customer_metrics, get_customer_rfm_segments,
get_customer_churn_risk, and get_product_performance are NOT exposed
here, on purpose -- they return one row per household (~2,500) or per
product (tens of thousands), which is too large to hand an LLM as a
single tool result and isn't how a business question gets asked anyway
("what's our churn risk?" means "give me the breakdown", not "list all
2,500 households"). Their *_summary / get_top_products counterparts are
exposed instead, which are already bounded. The raw functions are still
there for direct Python/notebook use -- they're just not wired into
chat.
"""

import pandas as pd

from src.analytics import churn, products, promotions, retention, revenue, segmentation


def _records(df: pd.DataFrame) -> list:
    return df.to_dict(orient="records")


TOOL_SPECS = [
    {
        "name": "get_monthly_revenue",
        "description": (
            "Total revenue, transaction count, unique customers, and average "
            "order value by calendar month, for the whole dataset (2016-01 "
            "through 2017-12). Use this for overall revenue trend questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_monthly_revenue_decomposition",
        "description": (
            "Each month's total revenue split into New, Retained, and "
            "Reactivated customer revenue, plus non-returning-customer "
            "revenue as context for the following month. Use this to explain "
            "WHY revenue moved -- e.g. whether a change came from new "
            "customer acquisition vs. existing customers buying more or less."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_monthly_revenue_anomalies",
        "description": (
            "Spike/Drop/Normal flag per month, based on a z-score against a "
            "trailing rolling baseline of up to 6 preceding months. 2016-01 "
            "and 2017-12 are flagged as known partial periods rather than "
            "scored. Use this to check whether a month's revenue was "
            "statistically unusual."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_monthly_cohort_retention",
        "description": (
            "Retention curve for each acquisition-month cohort: the share of "
            "households still active (>=1 transaction) in each subsequent "
            "calendar month. Use this for repeat-purchase / retention "
            "questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_segment_summary",
        "description": (
            "Household count and average revenue/orders/recency for each RFM "
            "(Recency/Frequency/Monetary) customer segment (e.g. Champions, "
            "At Risk, Hibernating). Use this for customer-base composition "
            "questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_top_products",
        "description": (
            "The N highest-revenue products, with department/brand/commodity "
            "descriptors and units sold. Use this for best-seller questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "How many top products to return. Defaults to 10.",
                }
            },
        },
    },
    {
        "name": "get_department_performance",
        "description": (
            "Revenue, units, and customer-reach rollup by department, with "
            "each department's share of total revenue. Use this for "
            "category/department-level questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_churn_summary",
        "description": (
            "Household count and average revenue/order metrics for each "
            "churn-risk category (Active/At Risk/Churned), where risk is "
            "based on each household's own historical purchase cadence, not "
            "a single global cutoff. This is retrospective (relative to the "
            "dataset's truncated end date), not a real-time signal. Use this "
            "for customer churn/retention-risk questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_promotion_lift_summary",
        "description": (
            "Overall (all products combined) average revenue and units per "
            "product/store/week when a product was promoted (on a store "
            "display and/or in the mailer) vs. not. Use this as the starting "
            "point for 'does promotion work' questions before drilling into "
            "specific products."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_product_promotion_lift",
        "description": (
            "Per-product revenue/units lift % when promoted vs. not, sorted "
            "highest lift first. Only includes products with at least 3 "
            "promoted and 3 not-promoted product/store/weeks of data. Use "
            "this to find which specific products respond best to "
            "promotion."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "How many products to return, ranked by revenue lift. Defaults to 20.",
                }
            },
        },
    },
]


def call_tool(name: str, tool_input: dict, engine) -> list:
    """Route a Claude tool-use request to the matching analytics function.

    Returns plain records (list of dicts) ready for JSON serialization.
    Raises ValueError for an unrecognized tool name -- the caller is
    expected to catch this and report it back to Claude as a tool error
    rather than letting it crash the conversation.
    """
    if name == "get_monthly_revenue":
        return _records(revenue.get_monthly_revenue(engine))
    if name == "get_monthly_revenue_decomposition":
        return _records(revenue.get_monthly_revenue_decomposition(engine))
    if name == "get_monthly_revenue_anomalies":
        return _records(revenue.get_monthly_revenue_anomalies(engine))
    if name == "get_monthly_cohort_retention":
        return _records(retention.get_monthly_cohort_retention(engine))
    if name == "get_segment_summary":
        return _records(segmentation.get_segment_summary(engine))
    if name == "get_top_products":
        n = int(tool_input.get("n", 10))
        return _records(products.get_top_products(engine, n=n))
    if name == "get_department_performance":
        return _records(products.get_department_performance(engine))
    if name == "get_churn_summary":
        return _records(churn.get_churn_summary(engine))
    if name == "get_promotion_lift_summary":
        return _records(promotions.get_promotion_lift_summary(engine))
    if name == "get_product_promotion_lift":
        limit = int(tool_input.get("limit", 20))
        return _records(promotions.get_product_promotion_lift(engine, limit=limit))
    raise ValueError(f"Unknown tool: {name}")
