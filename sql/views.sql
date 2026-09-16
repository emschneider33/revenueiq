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
