-- RevenueIQ — Analytical views
-- Run this after schema.sql has created the base tables and the ETL
-- script has loaded data. Views live here (separate from schema.sql)
-- since they can be dropped/recreated independently as metrics evolve.

USE revenueiq;

-- monthly_revenue: total revenue, order volume, and unique customers
-- by calendar month. This is the foundational metric everything else
-- (MoM comparisons, revenue decomposition) will build on.
DROP VIEW IF EXISTS monthly_revenue;

CREATE VIEW monthly_revenue AS
SELECT
    d.year_num,
    d.month_num,
    MIN(d.calendar_date)                    AS month_start_date,
    SUM(f.sales_value)                       AS total_revenue,
    COUNT(DISTINCT f.basket_id)              AS transaction_count,
    COUNT(DISTINCT f.household_key)          AS unique_customers,
    COUNT(*)                                  AS line_item_count,
    ROUND(SUM(f.sales_value) / COUNT(DISTINCT f.basket_id), 2) AS avg_order_value
FROM fact_transaction_line f
JOIN dim_date d ON f.day_number = d.day_number
GROUP BY d.year_num, d.month_num
ORDER BY d.year_num, d.month_num;

-- customer_metrics: per-household revenue, order volume, AOV, recency,
-- and tenure.
--
-- Reference point for recency/tenure: the dataset has no real "today" —
-- the raw DAY values are synthetic and the collection window simply
-- stops (see the Dec 2017 partial-month caveat in README.md). So both
-- recency and tenure are measured relative to the dataset's own last
-- transaction day (MAX(day_number) across all of fact_transaction_line),
-- not any real calendar date. This is the standard RFM convention of
-- using a fixed "snapshot" date:
--   recency_days = last_dataset_day - household's last_purchase_day
--   tenure_days  = last_dataset_day - household's first_purchase_day
-- (tenure here means "how long this household has been active as of
-- the end of the observation window", not "days between first and
-- last purchase" — if you want the latter, that's
-- last_purchase_day - first_purchase_day instead.)
--
-- Note: only households with at least one transaction appear here
-- (inner join via GROUP BY on fact_transaction_line) — a household_key
-- that exists in dim_household but never transacted will not get a row.
DROP VIEW IF EXISTS customer_metrics;

CREATE VIEW customer_metrics AS
WITH household_agg AS (
    SELECT
        f.household_key,
        SUM(f.sales_value)                AS total_revenue,
        COUNT(DISTINCT f.basket_id)        AS order_count,
        MIN(f.day_number)                  AS first_purchase_day,
        MAX(f.day_number)                  AS last_purchase_day
    FROM fact_transaction_line f
    GROUP BY f.household_key
),
dataset_bounds AS (
    SELECT MAX(day_number) AS last_dataset_day
    FROM fact_transaction_line
)
SELECT
    h.household_key,
    h.total_revenue,
    h.order_count,
    ROUND(h.total_revenue / h.order_count, 2)   AS avg_order_value,
    fd.calendar_date                             AS first_purchase_date,
    ld.calendar_date                             AS last_purchase_date,
    db.last_dataset_day - h.last_purchase_day    AS recency_days,
    db.last_dataset_day - h.first_purchase_day   AS tenure_days
FROM household_agg h
JOIN dim_date fd ON fd.day_number = h.first_purchase_day
JOIN dim_date ld ON ld.day_number = h.last_purchase_day
CROSS JOIN dataset_bounds db;

-- monthly_cohort_retention: cohort retention curve. Each household is
-- assigned to a cohort = the calendar month of its first-ever purchase.
-- For every cohort, this shows what share of that cohort was still
-- "active" (>=1 transaction) in each subsequent calendar month.
--
-- Definition notes:
--   - This is retail/repeat-purchase retention, not subscription
--     retention: "active" just means at least one transaction that
--     month, there's no churn event to detect.
--   - period_number = months elapsed since the cohort's acquisition
--     month (0 = the acquisition month itself, when by definition
--     every household in the cohort is active, so retention_rate = 1.0
--     at period_number = 0 for every cohort — a good invariant to spot
--     check).
--   - retention_rate = active_customers / cohort_size for that
--     (cohort, period_number) pair.
--
-- Caveats from README.md that hit this metric especially hard:
--   - Jan/Feb/Mar 2016 cohorts are inflated by the customer panel's
--     ramp-up (unique customers climb from 540 to 1,592 over those
--     three months) — that's not necessarily real new-customer
--     acquisition, so treat early-2016 cohort sizes with caution.
--   - The dataset's collection window ends 2017-12-11 (day_number 711),
--     11 days into what would be a partial December anyway. A "Dec
--     2017" cohort is built on almost no observation window, and any
--     cell whose activity month is Dec 2017 will undercount activity
--     for the same reason.
--   - Every cohort is right-censored at the end of the dataset: a
--     household acquired in Oct 2017 cannot show up at
--     period_number=6, because there is no Apr 2018 in the data. Don't
--     compare retention curves across cohorts past the point where the
--     older cohort runs out of calendar — the curve just stops
--     because time ran out, not because retention dropped to zero.
DROP VIEW IF EXISTS monthly_cohort_retention;

CREATE VIEW monthly_cohort_retention AS
WITH household_cohort AS (
    SELECT
        f.household_key,
        MIN(d.year_num * 12 + (d.month_num - 1)) AS cohort_period
    FROM fact_transaction_line f
    JOIN dim_date d ON f.day_number = d.day_number
    GROUP BY f.household_key
),
household_month_activity AS (
    SELECT DISTINCT
        f.household_key,
        d.year_num * 12 + (d.month_num - 1) AS activity_period
    FROM fact_transaction_line f
    JOIN dim_date d ON f.day_number = d.day_number
),
cohort_sizes AS (
    SELECT cohort_period, COUNT(*) AS cohort_size
    FROM household_cohort
    GROUP BY cohort_period
)
SELECT
    FLOOR(hc.cohort_period / 12)               AS cohort_year,
    MOD(hc.cohort_period, 12) + 1               AS cohort_month,
    hma.activity_period - hc.cohort_period      AS period_number,
    cs.cohort_size,
    COUNT(DISTINCT hma.household_key)           AS active_customers,
    ROUND(COUNT(DISTINCT hma.household_key) / cs.cohort_size, 4) AS retention_rate
FROM household_cohort hc
JOIN household_month_activity hma ON hma.household_key = hc.household_key
JOIN cohort_sizes cs ON cs.cohort_period = hc.cohort_period
GROUP BY hc.cohort_period, cs.cohort_size, hma.activity_period - hc.cohort_period
ORDER BY cohort_year, cohort_month, period_number;

-- customer_rfm_segments: RFM (Recency, Frequency, Monetary) segmentation
-- of households, built directly on customer_metrics.
--
-- Scoring: each of recency_days, order_count, and total_revenue is
-- bucketed into quintiles (NTILE(5)) across all households, so every
-- score is relative to this dataset's own customer base, not an
-- absolute business benchmark. Score 5 = best in every case:
--   r_score: 5 = most recent purchase (lowest recency_days)
--   f_score: 5 = most orders
--   m_score: 5 = highest total revenue
-- fm_score = average of f_score and m_score, collapsing frequency and
-- monetary onto a single "value" axis — the standard simplification
-- most RFM frameworks use, since the two are usually highly
-- correlated (see the sanity-check households below).
--
-- Segment labels are a simplified version of the common RFM segment
-- grid (fewer buckets than the full 11-segment version some marketing
-- tools use), chosen to stay easy to audit and retune rather than
-- matching any one external framework exactly. Thresholds are cut
-- points on the 1-5 score scale and can be adjusted here without
-- touching any underlying data:
--   Champions        - buy often/big AND recently   (r>=4, fm>=4)
--   Loyal Customers  - solid on both axes, not top-tier (r>=3, fm>=3)
--   Promising        - recent purchase, not yet frequent/high-value
--                      (r>=4, fm<3)
--   At Risk          - used to be valuable, hasn't purchased recently
--                      (r<3, fm>=4)
--   Hibernating      - low on both axes                (r<3, fm<3)
--   Needs Attention  - everyone else (mid-pack on one or both axes)
--
-- Caveat inherited from customer_metrics: recency_days is measured
-- against the dataset's truncated Dec 2017 end date (see README), so
-- r_score is compressed toward "recent" for anyone who shopped in the
-- last weeks of the dataset regardless of their real-world habits.
--
-- Performance: this view queries customer_metrics, which itself
-- re-aggregates the full fact table on every call (see Performance
-- notes in README.md) — expect the same cold-cache/warm-cache timing
-- behavior here as there.
DROP VIEW IF EXISTS customer_rfm_segments;

CREATE VIEW customer_rfm_segments AS
WITH scored AS (
    SELECT
        cm.household_key,
        cm.total_revenue,
        cm.order_count,
        cm.recency_days,
        cm.tenure_days,
        6 - NTILE(5) OVER (ORDER BY cm.recency_days ASC) AS r_score,
        NTILE(5) OVER (ORDER BY cm.order_count ASC)       AS f_score,
        NTILE(5) OVER (ORDER BY cm.total_revenue ASC)      AS m_score
    FROM customer_metrics cm
)
SELECT
    household_key,
    total_revenue,
    order_count,
    recency_days,
    tenure_days,
    r_score,
    f_score,
    m_score,
    ROUND((f_score + m_score) / 2, 1) AS fm_score,
    CASE
        WHEN r_score >= 4 AND (f_score + m_score) / 2 >= 4 THEN 'Champions'
        WHEN r_score >= 3 AND (f_score + m_score) / 2 >= 3 THEN 'Loyal Customers'
        WHEN r_score >= 4 AND (f_score + m_score) / 2 < 3  THEN 'Promising'
        WHEN r_score < 3  AND (f_score + m_score) / 2 >= 4 THEN 'At Risk'
        WHEN r_score < 3  AND (f_score + m_score) / 2 < 3  THEN 'Hibernating'
        ELSE 'Needs Attention'
    END AS rfm_segment
FROM scored;

-- product_performance: per-product revenue, units sold, transaction
-- count, and unique-customer reach, joined to dim_product's
-- descriptive fields (department, brand, commodity_desc,
-- sub_commodity_desc) for filtering and grouping.
--
-- Only products that appear in at least one transaction get a row
-- (inner join) -- dim_product's full ~92k-product catalog is not
-- reproduced here, only what actually sold.
--
-- Caveat to verify once this runs: fact_transaction_line's quantity
-- and sales_value are used as-is, with no filtering for returns. If
-- the raw Dunnhumby data includes negative quantity/sales_value rows
-- (returns), total_revenue and units_sold here are NET figures
-- (gross sales minus returns), not gross sales -- worth confirming
-- with a MIN(quantity)/MIN(sales_value) check on the fact table
-- before trusting "top products" rankings at face value.
DROP VIEW IF EXISTS product_performance;

CREATE VIEW product_performance AS
SELECT
    p.product_id,
    p.department,
    p.brand,
    p.commodity_desc,
    p.sub_commodity_desc,
    SUM(f.sales_value)                     AS total_revenue,
    SUM(f.quantity)                         AS units_sold,
    COUNT(DISTINCT f.basket_id)             AS transaction_count,
    COUNT(DISTINCT f.household_key)         AS unique_customers,
    ROUND(SUM(f.sales_value) / NULLIF(SUM(f.quantity), 0), 2) AS avg_unit_price
FROM fact_transaction_line f
JOIN dim_product p ON f.product_id = p.product_id
-- Grouping by product_id alone (not all five selected columns) matters
-- a lot here: product_id is dim_product's primary key, so department,
-- brand, commodity_desc, and sub_commodity_desc are all functionally
-- dependent on it -- MySQL allows selecting them ungrouped as a result.
-- Grouping by three VARCHAR columns in addition to product_id forced a
-- much more expensive string-based sort/group over 2.6M rows; grouping
-- by the single integer PK is dramatically cheaper for the same result.
GROUP BY p.product_id;

-- department_performance: revenue/units/customer-reach rollup by
-- department, plus each department's share of total revenue.
--
-- Deliberately independent of product_performance (aggregates
-- fact_transaction_line directly rather than summing it) so this
-- coarser-grained view isn't slowed down by product_performance's
-- ~92k-group aggregation -- department has far fewer distinct values.
DROP VIEW IF EXISTS department_performance;

CREATE VIEW department_performance AS
WITH dept_agg AS (
    SELECT
        p.department,
        SUM(f.sales_value)                  AS total_revenue,
        SUM(f.quantity)                       AS units_sold,
        COUNT(DISTINCT f.basket_id)           AS transaction_count,
        COUNT(DISTINCT f.household_key)       AS unique_customers,
        COUNT(DISTINCT p.product_id)          AS unique_products
    FROM fact_transaction_line f
    JOIN dim_product p ON f.product_id = p.product_id
    GROUP BY p.department
),
total AS (
    SELECT SUM(total_revenue) AS grand_total_revenue FROM dept_agg
)
SELECT
    d.department,
    d.total_revenue,
    ROUND(100 * d.total_revenue / t.grand_total_revenue, 2) AS revenue_share_pct,
    d.units_sold,
    d.transaction_count,
    d.unique_customers,
    d.unique_products,
    ROUND(d.total_revenue / NULLIF(d.units_sold, 0), 2)     AS avg_unit_price
FROM dept_agg d
CROSS JOIN total t
ORDER BY d.total_revenue DESC;

-- monthly_revenue_decomposition: breaks each month's total_revenue down
-- into how much came from New, Retained, and Reactivated households,
-- so MoM revenue changes can be explained by customer-base dynamics
-- rather than just reported as a single delta.
--
-- Per-household-per-month classification (mutually exclusive, and
-- together they account for 100% of that month's revenue):
--   New         - this is the household's first-ever purchase month
--                 (no earlier month_period exists for them at all)
--   Retained    - the household also purchased in the immediately
--                 preceding calendar month
--   Reactivated - the household purchased in some earlier month, but
--                 NOT in the immediately preceding month, and is back
--                 this month
--
-- non_returning_customer_revenue is a different cut, attached to the
-- month it was earned in: revenue from households who purchased THIS
-- month but do not purchase again next month. It answers "how much of
-- this month's revenue is at risk of not repeating" -- useful context
-- for the month right after it, but it is NOT part of the
-- new/retained/reactivated split above (a dollar can be both, e.g.
-- "Retained this month, but won't return next month").
--
-- Sanity check: new_customer_revenue + retained_customer_revenue +
-- reactivated_customer_revenue must equal total_revenue for every row,
-- and total_revenue here should match monthly_revenue.total_revenue
-- exactly for the same (year_num, month_num). The dataset's first
-- month (2016-01) should be 100% New, since no earlier month exists
-- for anyone to be Retained/Reactivated from.
--
-- This is a historical revenue bridge, not a churn forecast -- it
-- explains what already happened. Forward-looking churn risk is a
-- separate roadmap item.
DROP VIEW IF EXISTS monthly_revenue_decomposition;

CREATE VIEW monthly_revenue_decomposition AS
WITH household_monthly AS (
    SELECT
        f.household_key,
        d.year_num * 12 + (d.month_num - 1) AS month_period,
        d.year_num,
        d.month_num,
        SUM(f.sales_value) AS revenue
    FROM fact_transaction_line f
    JOIN dim_date d ON f.day_number = d.day_number
    GROUP BY f.household_key, month_period, d.year_num, d.month_num
),
household_first_month AS (
    SELECT household_key, MIN(month_period) AS first_month
    FROM household_monthly
    GROUP BY household_key
),
classified AS (
    SELECT
        hm.household_key,
        hm.month_period,
        hm.year_num,
        hm.month_num,
        hm.revenue,
        CASE
            WHEN hm.month_period = hf.first_month THEN 'New'
            WHEN prev.household_key IS NOT NULL THEN 'Retained'
            ELSE 'Reactivated'
        END AS customer_status,
        CASE WHEN nxt.household_key IS NULL THEN hm.revenue ELSE 0 END AS non_returning_revenue
    FROM household_monthly hm
    JOIN household_first_month hf ON hf.household_key = hm.household_key
    LEFT JOIN household_monthly prev
        ON prev.household_key = hm.household_key AND prev.month_period = hm.month_period - 1
    LEFT JOIN household_monthly nxt
        ON nxt.household_key = hm.household_key AND nxt.month_period = hm.month_period + 1
)
SELECT
    year_num,
    month_num,
    SUM(revenue)                                                                       AS total_revenue,
    SUM(CASE WHEN customer_status = 'New' THEN revenue ELSE 0 END)                      AS new_customer_revenue,
    COUNT(DISTINCT CASE WHEN customer_status = 'New' THEN household_key END)            AS new_customer_count,
    SUM(CASE WHEN customer_status = 'Retained' THEN revenue ELSE 0 END)                 AS retained_customer_revenue,
    COUNT(DISTINCT CASE WHEN customer_status = 'Retained' THEN household_key END)       AS retained_customer_count,
    SUM(CASE WHEN customer_status = 'Reactivated' THEN revenue ELSE 0 END)              AS reactivated_customer_revenue,
    COUNT(DISTINCT CASE WHEN customer_status = 'Reactivated' THEN household_key END)    AS reactivated_customer_count,
    SUM(non_returning_revenue)                                                          AS non_returning_customer_revenue,
    COUNT(DISTINCT CASE WHEN non_returning_revenue > 0 THEN household_key END)          AS non_returning_customer_count
FROM classified
GROUP BY year_num, month_num
ORDER BY year_num, month_num;

-- customer_churn_risk: classifies every household as Active, At Risk, or
-- Churned based on how their current recency_days compares to THEIR OWN
-- historical purchase cadence -- not a single global "days since last
-- purchase" cutoff, which would misclassify naturally infrequent
-- shoppers (e.g. a household that buys every 45 days isn't churned
-- just because it's been 40 days).
--
-- avg_days_between_purchases = tenure_days / (order_count - 1), i.e.
-- the average gap between this household's first and most recent
-- purchase, spread across their orders. Undefined for households with
-- only 1 order (or the rare case of 2+ orders all on the same day,
-- giving a 0-day gap that would make any recency look infinitely
-- overdue) -- both cases fall back to expected_purchase_gap_days, the
-- MEDIAN avg_days_between_purchases across all households with a
-- computable gap (MySQL has no MEDIAN()/PERCENTILE_CONT, so it's
-- computed via ROW_NUMBER()/COUNT() over a sorted window instead).
-- cadence_is_estimated flags every row using that fallback, so
-- low-confidence classifications are easy to filter out or discount.
--
-- Thresholds (recency_days vs. expected_purchase_gap_days):
--   Active   - recency_days <= 1.5x the expected gap (within normal
--              variation of their usual cycle)
--   At Risk  - recency_days between 1.5x and 3x the expected gap
--              (overdue, but not yet clearly gone)
--   Churned  - recency_days > 3x the expected gap
-- These multipliers are a starting heuristic, not a validated model --
-- easy to retune here once there's a way to check them against actual
-- outcomes.
--
-- Caveat inherited from customer_metrics: recency_days is measured
-- against the dataset's truncated Dec 2017 end date (see README), so
-- this is a historical/retrospective flag as of that snapshot, not a
-- real-time one -- and it under-penalizes households whose last
-- purchase fell right before the window closed, since there was little
-- time left in the data for them to return before we stopped counting.
DROP VIEW IF EXISTS customer_churn_risk;

CREATE VIEW customer_churn_risk AS
WITH gap_calc AS (
    SELECT
        cm.household_key,
        cm.total_revenue,
        cm.order_count,
        cm.recency_days,
        cm.tenure_days,
        CASE
            WHEN cm.order_count > 1 THEN cm.tenure_days / (cm.order_count - 1)
            ELSE NULL
        END AS avg_days_between_purchases
    FROM customer_metrics cm
),
ranked_gaps AS (
    SELECT
        avg_days_between_purchases,
        ROW_NUMBER() OVER (ORDER BY avg_days_between_purchases) AS rn,
        COUNT(*) OVER ()                                          AS cnt
    FROM gap_calc
    WHERE avg_days_between_purchases IS NOT NULL
      AND avg_days_between_purchases > 0
),
population_median AS (
    SELECT AVG(avg_days_between_purchases) AS median_gap
    FROM ranked_gaps
    WHERE rn IN (FLOOR((cnt + 1) / 2), CEIL((cnt + 1) / 2))
)
SELECT
    g.household_key,
    g.total_revenue,
    g.order_count,
    g.recency_days,
    g.tenure_days,
    g.avg_days_between_purchases,
    CASE
        WHEN g.avg_days_between_purchases IS NULL OR g.avg_days_between_purchases = 0 THEN TRUE
        ELSE FALSE
    END AS cadence_is_estimated,
    ROUND(COALESCE(NULLIF(g.avg_days_between_purchases, 0), pm.median_gap), 1) AS expected_purchase_gap_days,
    ROUND(g.recency_days / COALESCE(NULLIF(g.avg_days_between_purchases, 0), pm.median_gap), 2) AS recency_to_gap_ratio,
    CASE
        WHEN g.recency_days <= 1.5 * COALESCE(NULLIF(g.avg_days_between_purchases, 0), pm.median_gap) THEN 'Active'
        WHEN g.recency_days <= 3.0 * COALESCE(NULLIF(g.avg_days_between_purchases, 0), pm.median_gap) THEN 'At Risk'
        ELSE 'Churned'
    END AS churn_status
FROM gap_calc g
CROSS JOIN population_median pm;
