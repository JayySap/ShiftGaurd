"""Database initialization script for ShiftGuard.

This script initializes the database by executing the schema and seed SQL files.
It connects to the database using the DATABASE_URL environment variable.

Usage:
    poetry run python scripts/init_db.py
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


def get_project_root() -> Path:
    """Get the project root directory.

    Returns:
        Path to the project root.
    """
    return Path(__file__).parent.parent


def read_sql_file(filepath: Path) -> str:
    """Read SQL file contents.

    Args:
        filepath: Path to the SQL file.

    Returns:
        Contents of the SQL file.

    Raises:
        FileNotFoundError: If the file doesn't exist.
    """
    if not filepath.exists():
        raise FileNotFoundError(f"SQL file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def execute_sql(conn: psycopg2.extensions.connection, sql: str, description: str) -> None:
    """Execute SQL statements and commit.

    Args:
        conn: Database connection.
        sql: SQL statements to execute.
        description: Description for logging.

    Raises:
        psycopg2.Error: If execution fails.
    """
    print(f"Executing {description}...")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"  ✓ {description} completed successfully.")


def main() -> int:
    """Main entry point for database initialization.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    # Load environment variables from .env
    load_dotenv()

    # Get database URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable is not set.")
        print("Please create a .env file with your Neon database connection string.")
        return 1

    # Get project paths
    project_root = get_project_root()
    schema_path = project_root / "database" / "schema.sql"
    seed_path = project_root / "database" / "seed.sql"

    print("=" * 50)
    print("ShiftGuard Database Initialization")
    print("=" * 50)
    print(f"Project root: {project_root}")
    print(f"Schema file: {schema_path}")
    print(f"Seed file: {seed_path}")
    print()

    try:
        # Connect to database
        print("Connecting to database...")
        conn = psycopg2.connect(database_url)
        print("  ✓ Connected successfully.")
        print()

        # Step A: Execute schema.sql
        schema_sql = read_sql_file(schema_path)
        execute_sql(conn, schema_sql, "schema.sql")

        # Step B: Execute seed.sql
        seed_sql = read_sql_file(seed_path)
        execute_sql(conn, seed_sql, "seed.sql")

        # Verify data
        print()
        print("Verifying seeded data...")
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM employees")
            employee_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM availability")
            availability_count = cur.fetchone()[0]

        print(f"  ✓ Employees: {employee_count}")
        print(f"  ✓ Availability records: {availability_count}")

        conn.close()
        print()
        print("=" * 50)
        print("Database initialized and seeded successfully.")
        print("=" * 50)
        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
