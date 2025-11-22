"""Database reset script for ShiftGuard.

This script drops all tables and re-initializes the database with fresh schema and seed data.

Usage:
    poetry run python scripts/reset_db.py
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def read_sql_file(filepath: Path) -> str:
    """Read SQL file contents."""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def main() -> int:
    """Reset and reinitialize the database."""
    load_dotenv()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL not set")
        return 1

    project_root = get_project_root()
    schema_path = project_root / "database" / "schema.sql"
    seed_path = project_root / "database" / "seed.sql"

    print("=" * 50)
    print("ShiftGuard Database RESET")
    print("=" * 50)
    print()

    try:
        conn = psycopg2.connect(database_url)
        print("Connected to database.")

        # Drop all tables
        print("Dropping existing tables...")
        with conn.cursor() as cur:
            cur.execute("""
                DROP TABLE IF EXISTS shift_feedback CASCADE;
                DROP TABLE IF EXISTS shifts CASCADE;
                DROP TABLE IF EXISTS availability CASCADE;
                DROP TABLE IF EXISTS employees CASCADE;
            """)
        conn.commit()
        print("  ✓ Tables dropped.")

        # Re-create schema
        print("Executing schema.sql...")
        schema_sql = read_sql_file(schema_path)
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
        print("  ✓ Schema created.")

        # Re-seed data
        print("Executing seed.sql...")
        seed_sql = read_sql_file(seed_path)
        with conn.cursor() as cur:
            cur.execute(seed_sql)
        conn.commit()
        print("  ✓ Data seeded.")

        # Verify
        with conn.cursor() as cur:
            cur.execute("SELECT full_name, email FROM employees")
            employees = cur.fetchall()

        print()
        print("Employees in database:")
        for name, email in employees:
            print(f"  - {name}: {email}")

        conn.close()
        print()
        print("=" * 50)
        print("Database reset complete!")
        print("=" * 50)
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
