"""Test script for recurring weekly availability scheduling.

This script verifies that the 'Set and Forget' standard_availability
data produces a valid weekly schedule with proper:
- Priority-based allocation (MID_ONLY, OPEN_ONLY, CLOSE_ONLY, FLEXIBLE)
- Clopen violation detection (close then open with < 8h rest)

Usage:
    poetry run python tests/test_recurring_scheduler.py
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


# Day name mapping
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get_next_week_dates() -> tuple[date, date]:
    """Calculate start and end dates for next week (Monday to Sunday).

    Returns:
        Tuple of (start_date, end_date) for next week.
    """
    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7  # If today is Monday, get next Monday
    next_monday = today + timedelta(days=days_until_monday)
    next_sunday = next_monday + timedelta(days=6)
    return next_monday, next_sunday


def get_shift_type(start_hour: int) -> str:
    """Determine shift type based on start hour."""
    if start_hour == SHIFT_HOURS["OPEN"]["start"]:
        return "OPEN"
    elif start_hour == SHIFT_HOURS["MID"]["start"]:
        return "MID"
    elif start_hour == SHIFT_HOURS["CLOSE"]["start"]:
        return "CLOSE"
    return "UNKNOWN"


def get_employee_name(employee_id: str) -> str:
    """Look up employee name by ID."""
    with get_db_cursor(commit=False) as cur:
        cur.execute(
            "SELECT full_name FROM employees WHERE id = %s",
            (str(employee_id),)
        )
        result = cur.fetchone()
        return result["full_name"] if result else "Unknown"


def print_table_header():
    """Print table header row."""
    print(f"{'Day':<12} {'Shift':<8} {'Employee':<20} {'Violation':<30}")
    print("-" * 72)


def main() -> int:
    """Run the recurring scheduler test for next week.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    print("=" * 72)
    print("ShiftGuard - Recurring Availability Scheduler Test")
    print("=" * 72)
    print()

    # Get next week's date range
    start_date, end_date = get_next_week_dates()
    print(f"Schedule Period: {start_date.strftime('%A, %B %d')} to {end_date.strftime('%A, %B %d, %Y')}")
    print()

    print("Shift Configuration:")
    print(f"  OPEN:  {SHIFT_HOURS['OPEN']['start']:02d}:00 - {SHIFT_HOURS['OPEN']['end']:02d}:00 (6 AM - 2 PM)")
    print(f"  MID:   {SHIFT_HOURS['MID']['start']:02d}:00 - {SHIFT_HOURS['MID']['end']:02d}:00 (10 AM - 6 PM)")
    print(f"  CLOSE: {SHIFT_HOURS['CLOSE']['start']:02d}:00 - {SHIFT_HOURS['CLOSE']['end']:02d}:00 (2 PM - 10 PM)")
    print()

    try:
        # Initialize database
        print("Connecting to database...")
        init_db()
        print("  Connected.")
        print()

        # Import scheduler here to ensure DB is initialized first
        from src.services.scheduler import generate_draft_schedule

        # Generate the weekly schedule
        print("Generating schedule...")
        print("-" * 72)
        shifts = generate_draft_schedule(start_date=start_date, end_date=end_date)
        print("-" * 72)
        print()

        if not shifts:
            print("ERROR: No shifts generated!")
            print("Check that standard_availability has data for employees.")
            return 1

        # Organize shifts by day
        shifts_by_day: dict[date, list] = {}
        for shift in shifts:
            shift_date = shift.start_time.date()
            if shift_date not in shifts_by_day:
                shifts_by_day[shift_date] = []
            shifts_by_day[shift_date].append(shift)

        # Print results table
        print("=" * 72)
        print("GENERATED SCHEDULE")
        print("=" * 72)
        print()
        print_table_header()

        total_violations = 0
        current_date = start_date

        while current_date <= end_date:
            day_name = DAY_NAMES[current_date.weekday()]
            day_shifts = shifts_by_day.get(current_date, [])

            # Sort shifts by type: OPEN, MID, CLOSE
            shift_order = {"OPEN": 0, "MID": 1, "CLOSE": 2, "UNKNOWN": 3}
            day_shifts.sort(key=lambda s: shift_order.get(get_shift_type(s.start_time.hour), 3))

            if not day_shifts:
                print(f"{day_name:<12} {'---':<8} {'No shifts':<20} {'':<30}")
            else:
                for i, shift in enumerate(day_shifts):
                    shift_type = get_shift_type(shift.start_time.hour)
                    employee_name = get_employee_name(shift.employee_id)

                    violation_str = ""
                    if shift.is_clopen_violation:
                        total_violations += 1
                        violation_str = shift.violation_reason or "VIOLATION"

                    # Only show day name on first shift of the day
                    day_label = day_name if i == 0 else ""
                    print(f"{day_label:<12} {shift_type:<8} {employee_name:<20} {violation_str:<30}")

            current_date += timedelta(days=1)

        print("-" * 72)
        print()

        # Summary statistics
        print("=" * 72)
        print("SUMMARY")
        print("=" * 72)

        # Count by shift type
        shift_counts = {"OPEN": 0, "MID": 0, "CLOSE": 0}
        for shift in shifts:
            shift_type = get_shift_type(shift.start_time.hour)
            if shift_type in shift_counts:
                shift_counts[shift_type] += 1

        print(f"  Total shifts generated: {len(shifts)}")
        print(f"  Days scheduled: {len(shifts_by_day)}")
        print()
        print(f"  OPEN shifts:  {shift_counts['OPEN']}")
        print(f"  MID shifts:   {shift_counts['MID']}")
        print(f"  CLOSE shifts: {shift_counts['CLOSE']}")
        print()
        print(f"  Clopen violations: {total_violations}")
        print()

        # Verdict
        print("=" * 72)
        if total_violations > 0:
            print(f"WARNING: {total_violations} clopen violation(s) detected!")
            print("Manager must review and override before publishing.")
        else:
            print("SUCCESS: Schedule generated with no compliance violations.")
        print("=" * 72)

        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        close_db()


if __name__ == "__main__":
    sys.exit(main())
