"""RevenueIQ ETL — loads the Dunnhumby "Complete Journey" CSVs into MySQL.

Usage:
    python -m src.ingestion.load_data

Expects the 7 core CSVs to already be sitting in data/raw/:
    transaction_data.csv, product.csv, hh_demographic.csv,
    campaign_table.csv, campaign_desc.csv, coupon.csv, coupon_redempt.csv

(causal_data.csv is intentionally not loaded yet — see schema.sql notes.)

Load order matters because of foreign keys:
    dim_date -> dim_household -> dim_household_demographics -> dim_product
    -> dim_campaign -> dim_coupon -> bridge_campaign_household
    -> fact_transaction_line -> fact_coupon_redemption
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.ingestion.db import get_engine

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
ANCHOR_DATE = date(2016, 1, 1)  # day_number=1 maps to this date (arbitrary, documented)

TABLE_LOAD_ORDER = [
    "dim_date",
    "dim_household",
    "dim_household_demographics",
    "dim_product",
    "dim_campaign",
    "dim_coupon",
    "bridge_campaign_household",
    "fact_transaction_line",
    "fact_coupon_redemption",
]


def read_csv(filename: str) -> pd.DataFrame:
    """Read a raw CSV and normalize column names to lowercase."""
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Expected {filename} in {DATA_DIR}, but it wasn't found. "
            "Check that the Dunnhumby CSVs are in data/raw/."
        )
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def clear_existing_data(engine):
    """Truncate all tables (in FK-safe order) so this script can be re-run."""
    print("Clearing existing data for a clean reload...")
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in reversed(TABLE_LOAD_ORDER):
            conn.execute(text(f"TRUNCATE TABLE {table}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def build_dim_date(engine, max_day: int) -> None:
    print(f"Building dim_date for day_number 1..{max_day}...")
    rows = []
    for day_number in range(1, max_day + 1):
        calendar_date = ANCHOR_DATE + timedelta(days=day_number - 1)
        week_no = ((day_number - 1) // 7) + 1
        rows.append({
            "day_number": day_number,
            "calendar_date": calendar_date,
            "week_no": week_no,
            "year_num": calendar_date.year,
            "month_num": calendar_date.month,
            "day_of_week": calendar_date.isoweekday(),
        })
    df = pd.DataFrame(rows)
    df.to_sql("dim_date", engine, if_exists="append", index=False, chunksize=5000)
    print(f"  -> dim_date: {len(df)} rows loaded")


def load_dim_household(engine, household_keys: set) -> None:
    df = pd.DataFrame({"household_key": sorted(household_keys)})
    df.to_sql("dim_household", engine, if_exists="append", index=False, chunksize=5000)
    print(f"  -> dim_household: {len(df)} rows loaded")


def load_dim_household_demographics(engine) -> None:
    df = read_csv("hh_demographic.csv")
    df.to_sql("dim_household_demographics", engine, if_exists="append", index=False, chunksize=5000)
    print(f"  -> dim_household_demographics: {len(df)} rows loaded")


def load_dim_product(engine) -> None:
    df = read_csv("product.csv")
    df.to_sql("dim_product", engine, if_exists="append", index=False, chunksize=5000)
    print(f"  -> dim_product: {len(df)} rows loaded")


def load_dim_campaign(engine) -> None:
    df = read_csv("campaign_desc.csv")
    df = df.rename(columns={"start_day": "start_day", "end_day": "end_day"})
    df.to_sql("dim_campaign", engine, if_exists="append", index=False, chunksize=5000)
    print(f"  -> dim_campaign: {len(df)} rows loaded")


def load_dim_coupon(engine) -> None:
    df = read_csv("coupon.csv")
    before = len(df)
    df = df.drop_duplicates(subset=["coupon_upc", "campaign", "product_id"])
    dropped = before - len(df)
    if dropped:
        print(f"  (dropped {dropped} exact-duplicate rows from coupon.csv)")
    df.to_sql("dim_coupon", engine, if_exists="append", index=False, chunksize=5000)
    print(f"  -> dim_coupon: {len(df)} rows loaded")


def load_bridge_campaign_household(engine) -> None:
    df = read_csv("campaign_table.csv")
    df.to_sql("bridge_campaign_household", engine, if_exists="append", index=False, chunksize=5000)
    print(f"  -> bridge_campaign_household: {len(df)} rows loaded")


def load_fact_transaction_line(engine) -> pd.DataFrame:
    df = read_csv("transaction_data.csv")
    df = df.rename(columns={"day": "day_number"})
    keep_cols = [
        "household_key", "basket_id", "day_number", "product_id", "quantity",
        "sales_value", "store_id", "retail_disc", "trans_time", "week_no",
        "coupon_disc", "coupon_match_disc",
    ]
    df = df[keep_cols]
    print(f"Loading fact_transaction_line ({len(df):,} rows) — this is the big one, may take a few minutes...")
    df.to_sql("fact_transaction_line", engine, if_exists="append", index=False, chunksize=2000, method="multi")
    print(f"  -> fact_transaction_line: {len(df):,} rows loaded")
    return df


def load_fact_coupon_redemption(engine) -> None:
    df = read_csv("coupon_redempt.csv")
    df = df.rename(columns={"day": "day_number"})
    df.to_sql("fact_coupon_redemption", engine, if_exists="append", index=False, chunksize=5000)
    print(f"  -> fact_coupon_redemption: {len(df)} rows loaded")


def main():
    engine = get_engine()

    # Pre-read the files that determine dim_date's range and dim_household's membership,
    # so we don't have to read transaction_data.csv twice.
    transactions = read_csv("transaction_data.csv")
    hh_demo = read_csv("hh_demographic.csv")
    campaign_table = read_csv("campaign_table.csv")
    coupon_redempt = read_csv("coupon_redempt.csv")
    campaign_desc = read_csv("campaign_desc.csv")

    max_day = int(max(
        transactions["day"].max(),
        coupon_redempt["day"].max(),
        campaign_desc["end_day"].max(),
    ))

    household_keys = set(transactions["household_key"]) \
        | set(hh_demo["household_key"]) \
        | set(campaign_table["household_key"]) \
        | set(coupon_redempt["household_key"])

    clear_existing_data(engine)

    print("\nLoading dimension tables...")
    build_dim_date(engine, max_day)
    load_dim_household(engine, household_keys)
    load_dim_household_demographics(engine)
    load_dim_product(engine)
    load_dim_campaign(engine)
    load_dim_coupon(engine)

    print("\nLoading bridge table...")
    load_bridge_campaign_household(engine)

    print("\nLoading fact tables...")
    load_fact_transaction_line(engine)
    load_fact_coupon_redemption(engine)

    print("\nValidating row counts against MySQL...")
    with engine.connect() as conn:
        for table in TABLE_LOAD_ORDER:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table}: {count:,} rows in MySQL")

    print("\nETL complete.")


if __name__ == "__main__":
    main()
