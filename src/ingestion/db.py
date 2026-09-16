"""Database connection helper for RevenueIQ.

Reads MySQL credentials from environment variables (.env) and exposes
a single SQLAlchemy engine used by the rest of the ingestion pipeline.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

load_dotenv()


def get_engine() -> Engine:
    """Build a SQLAlchemy engine from .env credentials.

    Raises a clear error if any required variable is missing, rather
    than letting SQLAlchemy fail with an opaque connection error.
    """
    required = ["MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_DATABASE"]
    missing = [var for var in required if not os.getenv(var)]
    if missing:
        raise EnvironmentError(
            f"Missing required .env variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill in your MySQL credentials."
        )

    host = os.getenv("MYSQL_HOST")
    port = os.getenv("MYSQL_PORT")
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE")

    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    return create_engine(url)
