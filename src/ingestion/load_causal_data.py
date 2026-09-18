"""RevenueIQ ETL — loads causal_data.csv (promotional display/mailer
activity) into MySQL.

This is a SEPARATE, standalone script from load_data.py, not part of
the main Phase 1 pipeline. causal_data.csv is roughly 14x the row
count of transaction_data.csv (~696MB vs. ~142MB) and is only needed
for promotion-effectiveness analysis, so it's kept out of
load_data.py's main() and TABLE_LOAD_ORDER entirely -- running the
normal ETL never touches fact_causal_activity, and running this script
never touches anything else.

Usage:
    python -m src.ingestion.load_causal_data --limit 100000   # sanity check first
    python -m src.ingestion.load_causal_data                  # full load

Prerequisites:
    - fact_causal_activity must already exist in MySQL. This script
      does NOT create it -- run the CREATE TABLE statement from the
      bottom of sql/schema.sql once, by hand, before using this script.
    - dim_product must already be loaded (fact_causal_activity.product_id
      has a foreign key to dim_product.product_id).

This will take a while on the full run -- likely tens of minutes,
depending on hardware, since this file is much larger than anything
else in data/raw/. It reads and loads in chunks (rather than one
pd.read_csv() call) to keep memory use bounded and to report progress
as it goes, so a long run doesn't look hung. Run with --limit first
(e.g. --limit 100000) to confirm the column layout and load path work
in a few seconds before committing to the full run.
"""

import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.ingestion.db import get_engine

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
CSV_CHUNKSIZE = 500_000   # rows read from disk per pandas chunk
SQL_CHUNKSIZE = 5000      # rows per INSERT batch within to_sql, matching load_data.py
EXPECTED_COLUMNS = ["product_id", "store_id", "week_no", "display", "mailer"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load causal_data.csv into MySQL.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only load the first N rows -- for a quick sanity-check run "
             "before committing to the full (tens-of-minutes) load.",
    )
    return parser.parse_args()


def load_causal_data(engine, limit: int | None = None) -> int:
    path = DATA_DIR / "causal_data.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Expected causal_data.csv in {DATA_DIR}, but it wasn't found. "
            "Check that it's in data/raw/ alongside the other Dunnhumby CSVs."
        )

    total_rows = 0
    with engine.connect() as conn:
        print("Clearing any existing fact_causal_activity rows for a clean reload...")
        # FK checks disabled only around this table's bulk load -- same
        # pattern as clear_existing_data() in load_data.py -- so a
        # 30M+ row insert isn't paying a per-row FK lookup cost. Every
        # product_id here should already exist in dim_product (same
        # source dataset), but see the sanity-check queries for how to
        # confirm that after loading.
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        conn.execute(text("TRUNCATE TABLE fact_causal_activity"))
        conn.commit()

        reader = pd.read_csv(path, chunksize=CSV_CHUNKSIZE)
        for i, chunk in enumerate(reader, start=1):
            chunk.columns = [c.strip().lower() for c in chunk.columns]

            if i == 1:
                print(f"  Detected columns: {list(chunk.columns)}")
                missing = [c for c in EXPECTED_COLUMNS if c not in chunk.columns]
                if missing:
                    raise ValueError(
                        f"causal_data.csv is missing expected column(s): {missing}. "
                        f"Found: {list(chunk.columns)}. If Dunnhumby's column names "
                        "differ from what this script expects, update EXPECTED_COLUMNS "
                        "at the top of this file to match."
                    )

            chunk = chunk[EXPECTED_COLUMNS]

            if limit is not None:
                remaining = limit - total_rows
                if remaining <= 0:
                    break
                if len(chunk) > remaining:
                    chunk = chunk.head(remaining)

            chunk.to_sql(
                "fact_causal_activity", conn, if_exists="append",
                index=False, chunksize=SQL_CHUNKSIZE, method="multi",
            )
            conn.commit()
            total_rows += len(chunk)
            print(f"  -> fact_causal_activity: {total_rows:,} rows loaded so far (chunk {i})")

            if limit is not None and total_rows >= limit:
                break

        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.commit()

    return total_rows


def main():
    args = parse_args()
    engine = get_engine()

    if args.limit:
        print(f"Loading causal_data.csv (LIMITED to first {args.limit:,} rows -- sanity-check mode)...")
    else:
        print(
            "Loading causal_data.csv in full -- this file is large (~696MB) "
            "and will take a while (likely tens of minutes depending on "
            "hardware). Progress prints after every 500,000-row chunk, so if "
            "it looks quiet for a bit that's expected, not hung."
        )

    total = load_causal_data(engine, limit=args.limit)
    print(f"\nLoaded {total:,} rows into fact_causal_activity.")

    print("Validating row count against MySQL...")
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM fact_causal_activity")).scalar()
        print(f"  fact_causal_activity: {count:,} rows in MySQL")

    if args.limit:
        print("\nSanity-check load complete -- re-run without --limit for the full load.")
    else:
        print("\ncausal_data load complete.")


if __name__ == "__main__":
    main()
