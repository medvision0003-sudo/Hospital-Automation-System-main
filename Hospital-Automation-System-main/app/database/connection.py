# Database connection
import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()


def _build_database_url() -> str:
    """Resolve a database URL from environment variables.

    Supports the project's existing DATABASE_URL variable and a PostgreSQL
    POSTGRES_* tuple. When no database configuration is supplied and the app is
    not running in production, the project falls back to an SQLite file so local
    demo/test workflows still initialize cleanly.
    """
    configured_url = os.getenv("DATABASE_URL", "").strip()
    if configured_url:
        return configured_url

    postgres_host = os.getenv("POSTGRES_HOST", "").strip()
    postgres_port = os.getenv("POSTGRES_PORT", "5432").strip()
    postgres_db = os.getenv("POSTGRES_DB", "hospital_automation").strip()
    postgres_user = os.getenv("POSTGRES_USER", "postgres").strip()
    postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()

    if postgres_host or postgres_db or postgres_user:
        host = postgres_host or "localhost"
        db_name = postgres_db or "hospital_automation"
        username = postgres_user or "postgres"
        password = quote_plus(postgres_password)
        return (
            f"postgresql+psycopg2://{username}:{password}@{host}:"
            f"{postgres_port}/{db_name}"
        )

    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env != "production":
        return "sqlite:///./hospital_automation.db"

    raise RuntimeError(
        "Database configuration is missing. Set DATABASE_URL or POSTGRES_* "
        "variables, or run the app in demo mode with DEMO_MODE=true."
    )


DATABASE_URL = _build_database_url()
engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()