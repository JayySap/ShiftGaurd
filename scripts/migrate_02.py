"""Run migration 02 for recurring schema update.

Usage:
    poetry run python scripts/migrate_02.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return 1

    migration_file = Path(__file__).parent.parent / "database" / "migrations" / "02_recurring_schema.sql"

    print("=" * 60)
    print("Running Migration 02: Recurring Schema Update")
    print("=" * 60)
    print()
    print(f"Migration file: {migration_file.name}")

    try:
        sql_content = migration_file.read_text()
        print(f"SQL size: {len(sql_content)} bytes")
        print()

        conn = psycopg2.connect(database_url)
        cur = conn.cursor()

        cur.execute(sql_content)
        conn.commit()

        print("✓ Migration completed successfully")
        print()
        print("Day of week convention is now:")
        print("  0=Sunday, 1=Monday, 2=Tuesday, 3=Wednesday,")
        print("  4=Thursday, 5=Friday, 6=Saturday")

        cur.close()
        conn.close()
        return 0

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
