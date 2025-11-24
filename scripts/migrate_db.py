"""Database migration script for ShiftGuard.

This script runs SQL migration files against the Neon database.

Usage:
    poetry run python scripts/migrate_db.py [migration_file]

If no migration file is specified, runs all migrations in order.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


def get_migration_files() -> list[Path]:
    """Get all migration files in order.

    Returns:
        List of migration file paths sorted by name.
    """
    migrations_dir = Path(__file__).parent.parent / "database" / "migrations"
    if not migrations_dir.exists():
        print(f"Migrations directory not found: {migrations_dir}")
        return []

    files = sorted(migrations_dir.glob("*.sql"))
    return files


def run_migration(migration_path: Path) -> bool:
    """Run a single migration file.

    Args:
        migration_path: Path to the SQL migration file.

    Returns:
        True if successful, False otherwise.
    """
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return False

    print(f"Running migration: {migration_path.name}")
    print("-" * 50)

    try:
        # Read SQL file
        sql_content = migration_path.read_text()
        print(f"  SQL file size: {len(sql_content)} bytes")

        # Connect and execute
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()

        cur.execute(sql_content)
        conn.commit()

        print(f"  ✓ Migration completed successfully")

        cur.close()
        conn.close()
        return True

    except Exception as e:
        print(f"  ✗ Migration failed: {e}")
        return False


def main() -> int:
    """Run migrations.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    print("=" * 60)
    print("ShiftGuard Database Migration")
    print("=" * 60)
    print()

    # Check for specific migration file argument
    if len(sys.argv) > 1:
        migration_file = Path(sys.argv[1])
        if not migration_file.exists():
            # Try relative to migrations directory
            migrations_dir = Path(__file__).parent.parent / "database" / "migrations"
            migration_file = migrations_dir / sys.argv[1]

        if not migration_file.exists():
            print(f"Migration file not found: {sys.argv[1]}")
            return 1

        migrations = [migration_file]
    else:
        migrations = get_migration_files()

    if not migrations:
        print("No migrations found.")
        return 0

    print(f"Found {len(migrations)} migration(s) to run:")
    for m in migrations:
        print(f"  - {m.name}")
    print()

    # Run each migration
    success_count = 0
    fail_count = 0

    for migration in migrations:
        if run_migration(migration):
            success_count += 1
        else:
            fail_count += 1
        print()

    # Summary
    print("=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print(f"  Successful: {success_count}")
    print(f"  Failed: {fail_count}")
    print()

    if fail_count > 0:
        print("⚠ Some migrations failed!")
        return 1
    else:
        print("✓ All migrations completed successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
