"""Pytest configuration and global environment initialization for AuthOS."""
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    load_dotenv(env_path)

if "TEST_DATABASE_URL" not in os.environ:
    os.environ["TEST_DATABASE_URL"] = "postgresql+psycopg2://authos:authos@localhost:5433/authos_test"
