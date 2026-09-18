"""RevenueIQ -- Streamlit UI (Phase 5).

Two tabs:
  - Dashboard: charts and tables built directly from the analytics
    functions in src/analytics/ -- every number here is the same
    validated SQL-view output used everywhere else in this project.
    Nothing is computed in this file.
  - AI Analyst: a chat interface that reuses the exact tool-calling
    loop from src/ai/analyst.py (same system prompt, same tools, same
    dispatcher) -- this is not a separate/simplified version of the
    Phase 4 layer, it's the same one wrapped in a web UI instead of a
    terminal loop.

Run with:
    streamlit run app/streamlit_app.py

Chart colors are the validated categorical/status palette from the
dataviz skill (references/palette.md) -- fixed order, never reassigned
per-filter, status colors (good/warning/critical) reserved for
Active/At Risk/Churned and Spike/Drop rather than reused as "series 4".
"""

import sys
from pathlib import Path

# Streamlit runs this file directly (not via `python -m`), so the
# project root isn't automatically on sys.path the way it is for the
# `python -m src.ai.analyst` CLI. Add it so `from src...` imports work
# regardless of the directory `streamlit run` is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.ai.analyst import run_conversation
from src.analytics import churn, products, promotions, revenue, segmentation
from src.ingestion.db import get_engine

# ---------------------------------------------------------------------------
# Validated palette (dataviz skill, references/palette.md) -- plain hex
# since this is Python/Plotly, not the HTML/CSS custom-property setup the
# skill describes for web charts. Same values, same fixed categorical order.
# ---------------------------------------------------------------------------
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
MAGENTA, GREEN, VIOLET, RED = "#e87ba4", "#008300", "#4a3aa7", "#e34948"
CATEGORICAL = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]

STATUS_GOOD, STATUS_WARNING, STATUS_CRITICAL = "#0ca30c", "#fab219", "#d03b3b"

st.set_page_config(page_title="RevenueIQ", layout="wide")


# ---------------------------------------------------------------------------
# Cached resources (created once per session) and cached data (re-queried at
# most every 10 minutes) -- without this, every widget interaction would
# re-run every SQL query and re-create the DB engine / Anthropic client.
# ---------------------------------------------------------------------------
@st.cache_resource
def get_db_engine():
    return get_engine()


@st.cache_resource
def get_claude_client():
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


@st.cache_data(ttl=600)
def load_monthly_revenue():
    return revenue.get_monthly_revenue(get_db_engine())


@st.cache_data(ttl=600)
def load_revenue_anomalies():
    return revenue.get_monthly_revenue_anomalies(get_db_engine())


@st.cache_data(ttl=600)
def load_revenue_decomposition():
    return revenue.get_monthly_revenue_decomposition(get_db_engine())


@st.cache_data(ttl=600)
def load_segment_summary():
    return segmentation.get_segment_summary(get_db_engine())


@st.cache_data(ttl=600)
def load_churn_summary():
    return churn.get_churn_summary(get_db_engine())


@st.cache_data(ttl=600)
def load_top_products(n=10):
    return products.get_top_products(get_db_engine(), n=n)


@st.cache_data(ttl=600)
def load_department_performance():
    return products.get_department_performance(get_db_engine())


@st.cache_data(ttl=600)
def load_promotion_lift(limit=15):
    return promotions.get_product_promotion_lift(get_db_engine(), limit=limit)


@st.cache_data(ttl=600)
def load_promotion_summary():
    return promotions.get_promotion_lift_summary(get_db_engine())


def render_dashboard():
    st.title("RevenueIQ Dashboard")
    st.caption(
        "Dunnhumby \"Complete Journey\" grocery data -- 2,500 households, "
        "2016-01 through 2017-12-11. Every figure below comes directly from "
        "a validated SQL view (sql/views.sql); nothing here is estimated."
    )

    # ---- Monthly revenue trend, with anomaly markers ----------------------
    st.subheader("Monthly revenue")
    rev = load_monthly_revenue()
    anomalies = load_revenue_anomalies()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=rev["month_start_date"],
            y=rev["total_revenue"],
            mode="lines",
            name="Total revenue",
            line=dict(color=BLUE, width=2),
            hovertemplate="%{x|%b %Y}<br>$%{y:,.0f}<extra></extra>",
        )
    )
    spikes = anomalies[anomalies["anomaly_flag"] == "Spike"]
    drops = anomalies[anomalies["anomaly_flag"] == "Drop"]
    if not spikes.empty:
        fig.add_trace(
            go.Scatter(
                x=spikes["month_start_date"],
                y=spikes["total_revenue"],
                mode="markers",
                name="Spike",
                marker=dict(color=STATUS_GOOD, size=11, symbol="triangle-up"),
                hovertemplate="%{x|%b %Y}<br>Spike: $%{y:,.0f}<extra></extra>",
            )
        )
    if not drops.empty:
        fig.add_trace(
            go.Scatter(
                x=drops["month_start_date"],
                y=drops["total_revenue"],
                mode="markers",
                name="Drop",
                marker=dict(color=STATUS_CRITICAL, size=11, symbol="triangle-down"),
                hovertemplate="%{x|%b %Y}<br>Drop: $%{y:,.0f}<extra></extra>",
            )
        )
    fig.update_layout(
        height=380,
        margin=dict(t=10, b=10),
        yaxis_title="Revenue ($)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Jan 2016 and Dec 2017 are known partial periods (panel ramp-up / "
        "truncated collection window), not real anomalies -- see README."
    )

    col1, col2 = st.columns(2)

    # ---- Revenue decomposition ----------------------------------------------
    with col1:
        st.subheader("Revenue by customer status")
        decomp = load_revenue_decomposition()
        month_date = pd.to_datetime(
            dict(year=decomp["year_num"], month=decomp["month_num"], day=1)
        )
        fig2 = go.Figure()
        for col_name, label, color in [
            ("new_customer_revenue", "New", BLUE),
            ("retained_customer_revenue", "Retained", ORANGE),
            ("reactivated_customer_revenue", "Reactivated", AQUA),
        ]:
            fig2.add_trace(
                go.Bar(
                    x=month_date,
                    y=decomp[col_name],
                    name=label,
                    marker_color=color,
                    hovertemplate=f"%{{x|%b %Y}}<br>{label}: $%{{y:,.0f}}<extra></extra>",
                )
            )
        fig2.update_layout(
            barmode="stack",
            height=340,
            margin=dict(t=10, b=10),
            yaxis_title="Revenue ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
        st.plotly_chart(fig2, width="stretch")

    # ---- Churn risk -------------------------------------------------------
    with col2:
        st.subheader("Customer churn risk")
        churn_df = load_churn_summary()
        status_color_map = {
            "Active": STATUS_GOOD,
            "At Risk": STATUS_WARNING,
            "Churned": STATUS_CRITICAL,
        }
        fig3 = go.Figure(
            go.Bar(
                x=churn_df["churn_status"],
                y=churn_df["household_count"],
                marker_color=[status_color_map.get(s, BLUE) for s in churn_df["churn_status"]],
                hovertemplate="%{x}: %{y:,} households<extra></extra>",
            )
        )
        fig3.update_layout(height=340, margin=dict(t=10, b=10), yaxis_title="Households")
        st.plotly_chart(fig3, width="stretch")
        st.caption(
            "Retrospective, relative to the dataset's own truncated end date "
            "-- not a live churn signal."
        )

    col3, col4 = st.columns(2)

    # ---- RFM segments -------------------------------------------------------
    with col3:
        st.subheader("Customer segments (RFM)")
        seg = load_segment_summary().sort_values("household_count")
        fig4 = go.Figure(
            go.Bar(
                x=seg["household_count"],
                y=seg["rfm_segment"],
                orientation="h",
                marker_color=CATEGORICAL[: len(seg)],
                hovertemplate="%{y}: %{x:,} households<extra></extra>",
            )
        )
        fig4.update_layout(height=340, margin=dict(t=10, b=10), xaxis_title="Households")
        st.plotly_chart(fig4, width="stretch")

    # ---- Department performance ---------------------------------------------
    with col4:
        st.subheader("Revenue by department (top 10)")
        dept = load_department_performance().head(10).sort_values("total_revenue")
        fig5 = go.Figure(
            go.Bar(
                x=dept["total_revenue"],
                y=dept["department"],
                orientation="h",
                marker_color=BLUE,
                hovertemplate="%{y}: $%{x:,.0f}<extra></extra>",
            )
        )
        fig5.update_layout(height=340, margin=dict(t=10, b=10), xaxis_title="Revenue ($)")
        st.plotly_chart(fig5, width="stretch")

    # ---- Top products ---------------------------------------------------------
    st.subheader("Top 10 products by revenue")
    st.dataframe(load_top_products(10), width="stretch", hide_index=True)

    # ---- Promotion effectiveness ------------------------------------------------
    st.subheader("Promotion effectiveness")
    promo_summary = load_promotion_summary()
    promoted_row = promo_summary[promo_summary["promo_status"] == "Promoted"].iloc[0]
    not_promoted_row = promo_summary[promo_summary["promo_status"] == "Not Promoted"].iloc[0]

    c1, c2 = st.columns(2)
    c1.metric(
        "Avg revenue / product-store-week when promoted",
        f"${promoted_row['avg_revenue_per_product_store_week']:.2f}",
        f"{promoted_row['avg_revenue_per_product_store_week'] - not_promoted_row['avg_revenue_per_product_store_week']:+.2f} vs. not promoted",
    )
    c2.metric(
        "Avg units / product-store-week when promoted",
        f"{promoted_row['avg_units_per_product_store_week']:.2f}",
        f"{promoted_row['avg_units_per_product_store_week'] - not_promoted_row['avg_units_per_product_store_week']:+.2f} vs. not promoted",
    )

    lift = load_promotion_lift(15).sort_values("revenue_lift_pct")
    lift_labels = lift["product_id"].astype(str) + " (" + lift["commodity_desc"] + ")"
    lift_colors = [STATUS_GOOD if v >= 0 else STATUS_CRITICAL for v in lift["revenue_lift_pct"]]
    fig6 = go.Figure(
        go.Bar(
            x=lift["revenue_lift_pct"],
            y=lift_labels,
            orientation="h",
            marker_color=lift_colors,
            hovertemplate="%{y}<br>%{x:+.1f}% revenue lift<extra></extra>",
        )
    )
    fig6.update_layout(height=440, margin=dict(t=10, b=10), xaxis_title="Revenue lift %")
    st.plotly_chart(fig6, width="stretch")
    st.caption(
        "Top products by revenue lift when promoted vs. not (minimum 3 "
        "promoted and 3 not-promoted product-store-weeks). Excludes "
        "gas-station and misc-kiosk sales -- see README caveats."
    )


def render_chat():
    st.title("RevenueIQ Analyst")
    st.caption(
        "Ask a question about revenue, customers, products, or promotions. "
        "This uses the exact same tool-calling layer as the dashboard above "
        "-- Claude answers from real query results, it never computes a "
        "number itself."
    )

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []  # Claude API message format (sent back each turn)
    if "display_messages" not in st.session_state:
        st.session_state.display_messages = []  # (role, text) pairs, for rendering only

    for role, text in st.session_state.display_messages:
        with st.chat_message(role):
            st.markdown(text)

    question = st.chat_input("Ask about revenue, churn, products, promotions...")
    if question:
        st.session_state.display_messages.append(("user", question))
        with st.chat_message("user"):
            st.markdown(question)

        st.session_state.chat_messages.append({"role": "user", "content": question})

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                answer, st.session_state.chat_messages = run_conversation(
                    get_db_engine(), get_claude_client(), st.session_state.chat_messages
                )
            st.markdown(answer)
        st.session_state.display_messages.append(("assistant", answer))


def main():
    tab1, tab2 = st.tabs(["Dashboard", "AI Analyst"])
    with tab1:
        render_dashboard()
    with tab2:
        render_chat()


if __name__ == "__main__":
    main()
