-- RevenueIQ — MySQL Schema
-- Source: Dunnhumby "The Complete Journey" dataset
--
-- Notes on design decisions:
--   1. dim_date: the raw data has no calendar dates, only a relative
--      DAY integer (1 to ~711). We anchor day_number = 1 to 2016-01-01
--      (an arbitrary but documented choice) so we can compute real
--      calendar months/weeks/years for MoM/YoY analysis. This anchor
--      does not need to match reality — it just needs to be consistent.
--   2. dim_household vs dim_household_demographics: only ~801 of the
--      ~2,500 households in the dataset have demographic info. Keeping
--      demographics in a separate table makes that gap explicit rather
--      than burying it in NULLs across a wide table.
--   3. fact_transaction_line uses a surrogate auto-increment PK because
--      the same product can appear more than once within a single
--      basket (e.g. two separate line entries), so there's no natural
--      unique key across the raw columns alone.
--   4. causal_data (promotional display/mailer data) is intentionally
--      left out of this initial schema — it's large (~679MB) and only
--      needed once we build promotion-effectiveness analysis.

CREATE DATABASE IF NOT EXISTS revenueiq;
USE revenueiq;

-- ============================================================
-- DIMENSION TABLES
-- ============================================================

CREATE TABLE dim_date (
    day_number      INT PRIMARY KEY,          -- raw DAY value from the dataset (1-based)
    calendar_date   DATE NOT NULL,             -- day_number=1 anchored to 2016-01-01
    week_no         SMALLINT NOT NULL,         -- matches WEEK_NO in transaction_data
    year_num        SMALLINT NOT NULL,
    month_num       TINYINT NOT NULL,
    day_of_week     TINYINT NOT NULL,          -- 1=Monday ... 7=Sunday
    UNIQUE KEY uq_dim_date_calendar (calendar_date)
);

CREATE TABLE dim_household (
    household_key   INT PRIMARY KEY            -- every household seen anywhere in the data
);

CREATE TABLE dim_household_demographics (
    household_key           INT PRIMARY KEY,
    age_desc                VARCHAR(20),
    marital_status_code     VARCHAR(5),
    income_desc             VARCHAR(20),
    homeowner_desc          VARCHAR(30),
    hh_comp_desc             VARCHAR(30),
    household_size_desc     VARCHAR(10),
    kid_category_desc       VARCHAR(20),
    CONSTRAINT fk_demo_household
        FOREIGN KEY (household_key) REFERENCES dim_household(household_key)
);

CREATE TABLE dim_product (
    product_id          BIGINT PRIMARY KEY,
    manufacturer        INT,
    department           VARCHAR(50),
    brand                VARCHAR(20),           -- 'National' or 'Private'
    commodity_desc       VARCHAR(100),
    sub_commodity_desc   VARCHAR(100),
    curr_size_of_product VARCHAR(30)
);

CREATE TABLE dim_campaign (
    campaign        INT PRIMARY KEY,
    description     VARCHAR(10),                -- TypeA/B/C
    start_day       INT,
    end_day         INT,
    CONSTRAINT fk_campaign_start_day
        FOREIGN KEY (start_day) REFERENCES dim_date(day_number),
    CONSTRAINT fk_campaign_end_day
        FOREIGN KEY (end_day) REFERENCES dim_date(day_number)
);

-- Note: a single coupon_upc + campaign can apply to more than one
-- product_id (e.g. a coupon valid across a product group), so the
-- primary key needs all three columns, not just (coupon_upc, campaign).
CREATE TABLE dim_coupon (
    coupon_upc      BIGINT NOT NULL,
    campaign        INT NOT NULL,
    product_id      BIGINT NOT NULL,
    PRIMARY KEY (coupon_upc, campaign, product_id),
    CONSTRAINT fk_coupon_campaign
        FOREIGN KEY (campaign) REFERENCES dim_campaign(campaign),
    CONSTRAINT fk_coupon_product
        FOREIGN KEY (product_id) REFERENCES dim_product(product_id)
);

-- ============================================================
-- BRIDGE TABLE
-- ============================================================

CREATE TABLE bridge_campaign_household (
    campaign        INT NOT NULL,
    household_key   INT NOT NULL,
    description     VARCHAR(10),
    PRIMARY KEY (campaign, household_key),
    CONSTRAINT fk_bridge_campaign
        FOREIGN KEY (campaign) REFERENCES dim_campaign(campaign),
    CONSTRAINT fk_bridge_household
        FOREIGN KEY (household_key) REFERENCES dim_household(household_key)
);

-- ============================================================
-- FACT TABLES
-- ============================================================

CREATE TABLE fact_transaction_line (
    transaction_line_id  BIGINT AUTO_INCREMENT PRIMARY KEY,
    household_key        INT NOT NULL,
    basket_id             BIGINT NOT NULL,
    day_number            INT NOT NULL,
    product_id            BIGINT NOT NULL,
    quantity               INT,
    sales_value            DECIMAL(10,2),
    store_id               INT,
    retail_disc            DECIMAL(10,2),
    trans_time              SMALLINT,           -- raw HHMM value, e.g. 1631
    week_no                 SMALLINT,
    coupon_disc              DECIMAL(10,2),
    coupon_match_disc        DECIMAL(10,2),
    CONSTRAINT fk_txn_household
        FOREIGN KEY (household_key) REFERENCES dim_household(household_key),
    CONSTRAINT fk_txn_product
        FOREIGN KEY (product_id) REFERENCES dim_product(product_id),
    CONSTRAINT fk_txn_day
        FOREIGN KEY (day_number) REFERENCES dim_date(day_number),
    INDEX idx_txn_household (household_key),
    INDEX idx_txn_product (product_id),
    INDEX idx_txn_day (day_number),
    INDEX idx_txn_basket (basket_id)
);

-- Note: no FK to dim_coupon here. A redemption identifies a coupon_upc
-- redeemed under a campaign, but dim_coupon's key includes product_id
-- (since one coupon can cover multiple products), so (coupon_upc, campaign)
-- alone isn't a valid FK target there. We keep campaign's own FK to
-- dim_campaign for referential integrity on that piece.
CREATE TABLE fact_coupon_redemption (
    redemption_id   BIGINT AUTO_INCREMENT PRIMARY KEY,
    household_key   INT NOT NULL,
    day_number      INT NOT NULL,
    coupon_upc      BIGINT NOT NULL,
    campaign        INT NOT NULL,
    CONSTRAINT fk_redemption_household
        FOREIGN KEY (household_key) REFERENCES dim_household(household_key),
    CONSTRAINT fk_redemption_day
        FOREIGN KEY (day_number) REFERENCES dim_date(day_number),
    CONSTRAINT fk_redemption_campaign
        FOREIGN KEY (campaign) REFERENCES dim_campaign(campaign),
    INDEX idx_redemption_household (household_key)
);
