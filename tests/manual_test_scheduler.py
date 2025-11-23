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

from src.config import SHIFT_HOURS
from src.database import init_db, close_db, get_db_cursor
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
        'OPEN', 'MID', or 'CLOSE' string.
    """
    if start_hour == SHIFT_HOURS["OPEN"]["start"]:
        return "OPEN"
    elif start_hour == SHIFT_HOURS["MID"]["start"]:
        return "MID"
    elif start_hour == SHIFT_HOURS["CLOSE"]["start"]:
        return "CLOSE"
    else:
        return "UNKNOWN"


def get_employee_name(employee_id: str) -> str:
    """Look up employee name by ID.

    Args:
        employee_id: UUID of the employee.

    Returns:
        Employee's full name or 'Unknown'.
    """
    with get_db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT full_name FROM employees WHERE id = %s",
            (str(employee_id),)
        )
        result = cur.fetchone()
        return result["full_name"] if result else "Unknown"


def main() -> int:
    """Run the scheduler test.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    print("=" * 60)
    print("ShiftGuard - 3-Shift Scheduler Verification")
    print("=" * 60)
    print()
    print("Shift Configuration:")
    print(f"  OPEN:  {SHIFT_HOURS['OPEN']['start']:02d}:00 - {SHIFT_HOURS['OPEN']['end']:02d}:00")
    print(f"  MID:   {SHIFT_HOURS['MID']['start']:02d}:00 - {SHIFT_HOURS['MID']['end']:02d}:00")
    print(f"  CLOSE: {SHIFT_HOURS['CLOSE']['start']:02d}:00 - {SHIFT_HOURS['CLOSE']['end']:02d}:00")
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
        shifts_by_type = {"OPEN": [], "MID": [], "CLOSE": []}

        for shift in shifts:
            shift_type = get_shift_type(shift.start_time.hour)
            if shift_type in shifts_by_type:
                shifts_by_type[shift_type].append(shift)

        # Print shifts by type
        for shift_type in ["OPEN", "MID", "CLOSE"]:
            type_shifts = shifts_by_type[shift_type]
            print()
            print(f"{shift_type} SHIFTS ({len(type_shifts)} assigned)")
            print("-" * 40)
            if type_shifts:
                for shift in type_shifts:
                    employee_name = get_employee_name(shift.employee_id)
                    violation_flag = " ⚠️ VIOLATION" if shift.is_clopen_violation else ""
                    print(f"  • {employee_name}")
                    print(f"    Time: {format_shift_time(shift.start_time)} - {format_shift_time(shift.end_time)}")
                    print(f"    Status: {shift.status.value}{violation_flag}")
                    if shift.violation_reason:
                        print(f"    Reason: {shift.violation_reason}")
                    print()
            else:
                print("  (No shifts assigned)")
                print()

        # Summary
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        total_shifts = len(shifts)
        violations = sum(1 for s in shifts if s.is_clopen_violation)
        print(f"  Total shifts created: {total_shifts}")
        print(f"  Compliance violations flagged: {violations}")
        print(f"  OPEN shifts: {len(shifts_by_type['OPEN'])}")
        print(f"  MID shifts: {len(shifts_by_type['MID'])}")
        print(f"  CLOSE shifts: {len(shifts_by_type['CLOSE'])}")
        print()

        # Verification check
        print("=" * 60)
        print("VERIFICATION")
        print("=" * 60)

        # Check if Alex got MID shift
        alex_got_mid = False
        for shift in shifts_by_type["MID"]:
            name = get_employee_name(shift.employee_id)
            if "Alex" in name:
                alex_got_mid = True
                print(f"  ✓ Alex Mid assigned to MID shift (as expected)")
                break

        if not alex_got_mid and shifts_by_type["MID"]:
            mid_names = [get_employee_name(s.employee_id) for s in shifts_by_type["MID"]]
            print(f"  ⚠ MID shift assigned to: {', '.join(mid_names)}")

        # Check Mike got OPEN
        for shift in shifts_by_type["OPEN"]:
            name = get_employee_name(shift.employee_id)
            if "Mike" in name:
                print(f"  ✓ Mike Opener assigned to OPEN shift (as expected)")
                break

        # Check John got CLOSE
        for shift in shifts_by_type["CLOSE"]:
            name = get_employee_name(shift.employee_id)
            if "John" in name:
                print(f"  ✓ John Closer assigned to CLOSE shift (as expected)")
                break

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
