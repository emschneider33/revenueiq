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
