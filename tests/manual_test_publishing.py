"""Manual integration test for calendar publishing.

This script tests the publish_shifts function by:
1. Creating a dummy shift for tomorrow
2. Setting its status to PUBLISHED
3. Calling publish_shifts()
4. Verifying the result

Usage:
    poetry run python tests/manual_test_publishing.py
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# Load environment variables before importing app modules
load_dotenv()

from src.database import init_db, close_db, get_db_cursor
from src.services.calendar import publish_shifts


def get_sarah_employee_id() -> UUID:
    """Get Sarah Barista's employee ID from the database.

    Returns:
        UUID of Sarah's employee record.

    Raises:
        ValueError: If Sarah is not found in the database.
    """
    with get_db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT id, email FROM employees WHERE full_name = 'Sarah Barista'"
        )
        result = cur.fetchone()
        if not result:
            raise ValueError("Sarah Barista not found in database. Run scripts/reset_db.py first.")
        print(f"  Found Sarah: {result['email']}")
        return UUID(str(result["id"]))


def create_test_shift(employee_id: UUID) -> UUID:
    """Create a test shift for tomorrow 9 AM - 5 PM.

    Args:
        employee_id: UUID of the employee to assign the shift to.

    Returns:
        UUID of the created shift.
    """
    tomorrow = date.today() + timedelta(days=1)

    # Create shift times (9 AM - 5 PM)
    start_time = datetime(
        tomorrow.year, tomorrow.month, tomorrow.day,
        9, 0, 0, tzinfo=timezone.utc
    )
    end_time = datetime(
        tomorrow.year, tomorrow.month, tomorrow.day,
        17, 0, 0, tzinfo=timezone.utc
    )

    with get_db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO shifts (employee_id, start_time, end_time, status)
            VALUES (%s, %s, %s, 'DRAFT')
            RETURNING id
            """,
            (str(employee_id), start_time, end_time),
        )
        result = cur.fetchone()
        shift_id = UUID(str(result["id"]))

    print(f"  Created shift: {shift_id}")
    print(f"  Time: {start_time.strftime('%Y-%m-%d %I:%M %p')} - {end_time.strftime('%I:%M %p')}")

    return shift_id


def set_shift_published(shift_id: UUID) -> None:
    """Update shift status to PUBLISHED.

    Args:
        shift_id: UUID of the shift to publish.
    """
    with get_db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE shifts SET status = 'PUBLISHED' WHERE id = %s",
            (str(shift_id),),
        )
    print(f"  Shift {shift_id} status set to PUBLISHED")


def verify_shift_status(shift_id: UUID) -> str:
    """Check the current status of a shift.

    Args:
        shift_id: UUID of the shift to check.

    Returns:
        Current status string.
    """
    with get_db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT status FROM shifts WHERE id = %s",
            (str(shift_id),),
        )
        result = cur.fetchone()
        return result["status"] if result else "NOT_FOUND"


def cleanup_test_shift(shift_id: UUID) -> None:
    """Delete the test shift.

    Args:
        shift_id: UUID of the shift to delete.
    """
    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM shifts WHERE id = %s", (str(shift_id),))
    print(f"  Cleaned up test shift: {shift_id}")


def main() -> int:
    """Run the publishing integration test.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    print("=" * 60)
    print("ShiftGuard - Calendar Publishing Integration Test")
    print("=" * 60)
    print()

    shift_id = None

    try:
        # Initialize database
        print("Step 1: Initializing database connection...")
        init_db()
        print("  ✓ Database connected")
        print()

        # Get Sarah's employee ID
        print("Step 2: Looking up Sarah Barista...")
        employee_id = get_sarah_employee_id()
        print()

        # Create test shift
        print("Step 3: Creating test shift for tomorrow 9 AM - 5 PM...")
        shift_id = create_test_shift(employee_id)
        print()

        # Set shift to PUBLISHED
        print("Step 4: Setting shift status to PUBLISHED...")
        set_shift_published(shift_id)
        print()

        # Execute publish_shifts
        print("Step 5: Calling publish_shifts()...")
        print("-" * 60)
        tomorrow = date.today() + timedelta(days=1)
        result = publish_shifts(start_date=tomorrow, end_date=tomorrow)
        print("-" * 60)
        print()

        # Display results
        print("=" * 60)
        print("RESULTS")
        print("=" * 60)
        print(f"  Sent: {result['sent']}")
        print(f"  Errors: {result['errors']}")
        print()

        # Verify status change
        final_status = verify_shift_status(shift_id)
        print(f"  Final shift status: {final_status}")
        print()

        if result["sent"] > 0 and final_status == "AWAITING_RESPONSE":
            print("✓ SUCCESS! Calendar invite should appear in your inbox.")
            print("  Check saprajayant@gmail.com for the invite.")
            return 0
        elif result["sent"] > 0:
            print("⚠ Partial success - invite sent but status not updated")
            return 0
        else:
            print("✗ FAILED - No invites were sent")
            print("  Check the error messages above for details.")
            return 1

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Optionally cleanup (comment out to keep test data)
        # if shift_id:
        #     print()
        #     print("Cleaning up...")
        #     cleanup_test_shift(shift_id)

        close_db()
        print()
        print("=" * 60)
        print("Test complete!")
        print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
