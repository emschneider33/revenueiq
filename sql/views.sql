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
