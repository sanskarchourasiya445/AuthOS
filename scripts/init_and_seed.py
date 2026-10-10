"""Idempotent database migration and synthetic data seeding CLI script.

Usage:
    python scripts/init_and_seed.py [--skip-migrations]
"""
import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.db.seed import seed_synthetic_data
from backend.db.session import SessionLocal, get_db_session
from backend.rag.ingest import ingest_synthetic_records


def run_migrations() -> None:
    """Apply Alembic migrations to latest head."""
    print(f"[AuthOS Deploy] Running Alembic migrations on target: {settings.get_sanitized_database_url()}...")
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    print("[AuthOS Deploy] Migrations successfully upgraded to head.")


def seed_database() -> dict[str, int]:
    """Seed synthetic clinical data and chunk records idempotently."""
    print("[AuthOS Deploy] Seeding synthetic policy, patient, and case records...")
    with get_db_session() as session:
        seed_counts = seed_synthetic_data(session)
        chunk_count = ingest_synthetic_records(session)
    print(f"[AuthOS Deploy] Seeding complete: {seed_counts}")
    print(f"[AuthOS Deploy] Chunk ingestion complete: {chunk_count} chunks persisted.")
    return {**seed_counts, "chunks": chunk_count}


def verify_database() -> bool:
    """Probe database connectivity."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        print(f"[AuthOS Deploy] Database check failed: {exc}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="AuthOS Database Migration and Seeding Utility")
    parser.add_argument("--skip-migrations", action="store_true", help="Skip running Alembic migrations")
    args = parser.parse_args()

    if not verify_database():
        sys.exit(1)

    if not args.skip_migrations:
        run_migrations()

    seed_database()
    print("[AuthOS Deploy] Ready for operation.")


if __name__ == "__main__":
    main()
