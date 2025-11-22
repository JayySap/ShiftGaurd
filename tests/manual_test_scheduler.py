"""Manual test script to verify scheduler logic.

This script tests the generate_draft_schedule function by creating
a schedule for tomorrow and printing the results.

Usage:
    poetry run python tests/manual_test_scheduler.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# Load environment variables before importing app modules
load_dotenv()

from src.database import init_db, close_db
from src.services.scheduler import generate_draft_schedule


def format_shift_time(dt) -> str:
    """Format datetime for display.

    Args:
        dt: Datetime object to format.

    Returns:
        Formatted time string.
    """
    return dt.strftime("%I:%M %p")


def get_shift_type(start_hour: int) -> str:
    """Determine shift type based on start hour.

    Args:
        start_hour: Hour of shift start (0-23).

    Returns:
        'OPENING' or 'CLOSING' string.
    """
    return "OPENING" if start_hour < 12 else "CLOSING"


def main() -> int:
    """Run the scheduler test.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    print("=" * 60)
    print("ShiftGuard - Scheduler Logic Verification")
    print("=" * 60)
    print()

    # Calculate tomorrow's date
    tomorrow = date.today() + timedelta(days=1)
    print(f"Generating schedule for: {tomorrow.strftime('%A, %B %d, %Y')}")
    print()

    try:
        # Initialize database connection pool
        print("Initializing database connection...")
        init_db()
        print("  ✓ Database connected.")
        print()

        # Generate the schedule
        print("Running generate_draft_schedule()...")
        print("-" * 60)
        shifts = generate_draft_schedule(start_date=tomorrow, end_date=tomorrow)
        print("-" * 60)
        print()

        # Display results
        print("=" * 60)
        print("GENERATED SHIFTS")
        print("=" * 60)

        if not shifts:
            print("No shifts were generated.")
            print("This could mean:")
            print("  - No availability records for tomorrow")
            print("  - All candidates exceeded weekly hours")
            return 1

        # Group shifts by type
        opening_shifts = []
        closing_shifts = []

        for shift in shifts:
            shift_type = get_shift_type(shift.start_time.hour)
            if shift_type == "OPENING":
                opening_shifts.append(shift)
            else:
                closing_shifts.append(shift)

        # Print opening shifts
        print()
        print(f"OPENING SHIFTS ({len(opening_shifts)} assigned)")
        print("-" * 40)
        if opening_shifts:
            for shift in opening_shifts:
                violation_flag = " ⚠️ VIOLATION" if shift.is_clopen_violation else ""
                print(f"  • Employee ID: {shift.employee_id}")
                print(f"    Time: {format_shift_time(shift.start_time)} - {format_shift_time(shift.end_time)}")
                print(f"    Status: {shift.status.value}{violation_flag}")
                if shift.violation_reason:
                    print(f"    Reason: {shift.violation_reason}")
                print()
        else:
            print("  (No opening shifts assigned)")
            print()

        # Print closing shifts
        print(f"CLOSING SHIFTS ({len(closing_shifts)} assigned)")
        print("-" * 40)
        if closing_shifts:
            for shift in closing_shifts:
                violation_flag = " ⚠️ VIOLATION" if shift.is_clopen_violation else ""
                print(f"  • Employee ID: {shift.employee_id}")
                print(f"    Time: {format_shift_time(shift.start_time)} - {format_shift_time(shift.end_time)}")
                print(f"    Status: {shift.status.value}{violation_flag}")
                if shift.violation_reason:
                    print(f"    Reason: {shift.violation_reason}")
                print()
        else:
            print("  (No closing shifts assigned)")
            print()

        # Summary
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        total_shifts = len(shifts)
        violations = sum(1 for s in shifts if s.is_clopen_violation)
        print(f"  Total shifts created: {total_shifts}")
        print(f"  Compliance violations flagged: {violations}")
        print(f"  Opening shifts: {len(opening_shifts)}")
        print(f"  Closing shifts: {len(closing_shifts)}")
        print()

        if violations > 0:
            print("⚠️  WARNING: Some shifts have compliance violations!")
            print("    Manager override required before publishing.")
        else:
            print("✓ All shifts comply with BC/Ontario labor laws.")

        print()
        print("=" * 60)
        print("Scheduler logic verification COMPLETE")
        print("=" * 60)

        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Clean up database connections
        close_db()


if __name__ == "__main__":
    sys.exit(main())
