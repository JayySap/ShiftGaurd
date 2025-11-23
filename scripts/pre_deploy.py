"""Pre-deployment verification script for ShiftGuard.

This script runs checks to ensure the application is ready for deployment:
1. Database connectivity
2. Required environment variables
3. Composio connection (optional)

Usage:
    poetry run python scripts/pre_deploy.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


def check_env_variables() -> tuple[bool, list[str]]:
    """Check that all required environment variables are set.

    Returns:
        Tuple of (success, list of missing variables).
    """
    required_vars = [
        "DATABASE_URL",
    ]

    optional_vars = [
        "COMPOSIO_API_KEY",
        "FLASK_SECRET_KEY",
        "CRON_SECRET",
    ]

    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)

    warnings = []
    for var in optional_vars:
        if not os.getenv(var):
            warnings.append(var)

    return len(missing) == 0, missing, warnings


def check_database_connection() -> tuple[bool, str]:
    """Test database connectivity.

    Returns:
        Tuple of (success, error message or success message).
    """
    try:
        import psycopg2

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return False, "DATABASE_URL not set"

        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()

        # Test query
        cursor.execute("SELECT COUNT(*) FROM employees")
        count = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return True, f"Connected successfully. {count} employees in database."

    except Exception as e:
        return False, str(e)


def check_composio_connection() -> tuple[bool, str]:
    """Test Composio API connectivity.

    Returns:
        Tuple of (success, error message or success message).
    """
    api_key = os.getenv("COMPOSIO_API_KEY")
    if not api_key:
        return False, "COMPOSIO_API_KEY not set (calendar integration will fail)"

    try:
        from composio import ComposioToolSet

        toolset = ComposioToolSet(api_key=api_key)
        connections = toolset.client.connected_accounts.get()

        gcal_conn = next(
            (c for c in connections if c.appName == "googlecalendar" and c.status == "ACTIVE"),
            None
        )

        if gcal_conn:
            return True, f"Google Calendar connected (ID: {gcal_conn.id[:8]}...)"
        else:
            return False, "No active Google Calendar connection found"

    except Exception as e:
        return False, str(e)


def main() -> int:
    """Run all pre-deployment checks.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    print("=" * 60)
    print("ShiftGuard Pre-Deployment Checks")
    print("=" * 60)
    print()

    all_passed = True

    # Check 1: Environment Variables
    print("1. Checking environment variables...")
    env_ok, missing, warnings = check_env_variables()
    if env_ok:
        print("   ✓ All required environment variables set")
    else:
        print(f"   ✗ Missing required variables: {', '.join(missing)}")
        all_passed = False

    if warnings:
        print(f"   ⚠ Optional variables not set: {', '.join(warnings)}")
    print()

    # Check 2: Database Connection
    print("2. Checking database connection...")
    db_ok, db_msg = check_database_connection()
    if db_ok:
        print(f"   ✓ {db_msg}")
    else:
        print(f"   ✗ Database error: {db_msg}")
        all_passed = False
    print()

    # Check 3: Composio Connection
    print("3. Checking Composio connection...")
    composio_ok, composio_msg = check_composio_connection()
    if composio_ok:
        print(f"   ✓ {composio_msg}")
    else:
        print(f"   ⚠ {composio_msg}")
        # Don't fail deployment for Composio - it's needed for calendar but not core functionality
    print()

    # Summary
    print("=" * 60)
    if all_passed:
        print("✓ All critical checks passed. Ready for deployment!")
        print("=" * 60)
        return 0
    else:
        print("✗ Some checks failed. Fix issues before deploying.")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
