"""Schedule generation service for ShiftGuard.

This module contains the core scheduling logic that generates draft schedules
while respecting labor law compliance requirements (BC/Ontario).
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from src.config import settings
from src.database import get_db_cursor
from src.models.schemas import Shift, ShiftCreate, ShiftStatus

logger = logging.getLogger(__name__)

# MVP Hardcoded Shift Requirements
# Format: {day_of_week: {"openers": count, "closers": count}}
# 0 = Monday, 6 = Sunday
SHIFT_REQUIREMENTS: dict[int, dict[str, int]] = {
    0: {"openers": 2, "closers": 2},  # Monday
    1: {"openers": 2, "closers": 2},  # Tuesday
    2: {"openers": 2, "closers": 2},  # Wednesday
    3: {"openers": 2, "closers": 2},  # Thursday
    4: {"openers": 2, "closers": 3},  # Friday
    5: {"openers": 2, "closers": 3},  # Saturday
    6: {"openers": 2, "closers": 2},  # Sunday
}

# Default shift times (can be overridden via config in future)
OPENING_SHIFT_START = 5  # 5:00 AM
OPENING_SHIFT_END = 13  # 1:00 PM
CLOSING_SHIFT_START = 13  # 1:00 PM
CLOSING_SHIFT_END = 22  # 10:00 PM


class ComplianceViolation:
    """Represents a labor law compliance violation.

    Attributes:
        rule_code: Identifier for the violated rule (e.g., 'REST_PERIOD').
        description: Human-readable explanation of the violation.
        severity: 'WARNING' or 'CRITICAL'.
    """

    def __init__(self, rule_code: str, description: str, severity: str = "WARNING"):
        """Initialize a compliance violation.

        Args:
            rule_code: Identifier for the violated rule.
            description: Human-readable explanation.
            severity: 'WARNING' or 'CRITICAL'.
        """
        self.rule_code = rule_code
        self.description = description
        self.severity = severity


def get_availability_for_range(
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Fetch all availability records for a date range.

    Args:
        start_date: Start of the date range (inclusive).
        end_date: End of the date range (inclusive).

    Returns:
        List of availability records with employee information.

    Raises:
        Exception: If database query fails.
    """
    with get_db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT
                a.id,
                a.employee_id,
                a.shift_date,
                a.can_open,
                a.can_close,
                a.note,
                e.full_name,
                e.email,
                e.max_weekly_hours,
                e.waived_notice_period
            FROM availability a
            JOIN employees e ON a.employee_id = e.id
            WHERE a.shift_date BETWEEN %s AND %s
              AND e.is_active = TRUE
            ORDER BY a.shift_date, e.full_name
            """,
            (start_date, end_date),
        )
        return [dict(row) for row in cur.fetchall()]


def get_recent_shifts(
    employee_id: UUID,
    before_datetime: datetime,
    hours_lookback: int = 24,
) -> list[dict[str, Any]]:
    """Fetch shifts for an employee within a lookback period.

    Used to check for clopening violations and rest period compliance.

    Args:
        employee_id: The employee's UUID.
        before_datetime: The reference datetime to look back from.
        hours_lookback: Number of hours to look back (default 24).

    Returns:
        List of recent shift records.

    Raises:
        Exception: If database query fails.
    """
    lookback_start = before_datetime - timedelta(hours=hours_lookback)

    with get_db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT id, employee_id, start_time, end_time, status
            FROM shifts
            WHERE employee_id = %s
              AND end_time BETWEEN %s AND %s
            ORDER BY end_time DESC
            """,
            (str(employee_id), lookback_start, before_datetime),
        )
        return [dict(row) for row in cur.fetchall()]


def get_weekly_hours(
    employee_id: UUID,
    week_start: date,
) -> float:
    """Calculate total scheduled hours for an employee in a week.

    Args:
        employee_id: The employee's UUID.
        week_start: The Monday of the week to check.

    Returns:
        Total scheduled hours for the week.

    Raises:
        Exception: If database query fails.
    """
    week_end = week_start + timedelta(days=6)

    with get_db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT COALESCE(
                SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 3600),
                0
            ) as total_hours
            FROM shifts
            WHERE employee_id = %s
              AND DATE(start_time) BETWEEN %s AND %s
              AND status NOT IN ('DECLINED')
            """,
            (str(employee_id), week_start, week_end),
        )
        result = cur.fetchone()
        return float(result["total_hours"]) if result else 0.0


def check_rest_period_violation(
    employee_id: UUID,
    proposed_start: datetime,
) -> Optional[ComplianceViolation]:
    """Check if a proposed shift violates minimum rest period rules.

    Rule A: Employee must have at least MIN_REST_HOURS between shifts.

    Args:
        employee_id: The employee's UUID.
        proposed_start: The proposed shift start time.

    Returns:
        ComplianceViolation if rest period is violated, None otherwise.
    """
    recent_shifts = get_recent_shifts(
        employee_id,
        proposed_start,
        hours_lookback=settings.min_rest_hours + 12,
    )

    if not recent_shifts:
        return None

    last_shift = recent_shifts[0]
    last_end = last_shift["end_time"]

    # Handle timezone-aware comparison
    if last_end.tzinfo is None:
        last_end = last_end.replace(tzinfo=timezone.utc)
    if proposed_start.tzinfo is None:
        proposed_start = proposed_start.replace(tzinfo=timezone.utc)

    rest_hours = (proposed_start - last_end).total_seconds() / 3600

    if rest_hours < settings.min_rest_hours:
        return ComplianceViolation(
            rule_code="REST_PERIOD",
            description=f"Rest period {rest_hours:.1f}h < {settings.min_rest_hours}h minimum",
            severity="WARNING",
        )

    return None


def check_weekly_rest_violation(
    employee_id: UUID,
    week_start: date,
) -> Optional[ComplianceViolation]:
    """Check if employee has had required consecutive rest in the week.

    Rule B: Employee must have MIN_WEEKLY_REST_HOURS consecutive hours off.

    Args:
        employee_id: The employee's UUID.
        week_start: The Monday of the week to check.

    Returns:
        ComplianceViolation if weekly rest is violated, None otherwise.
    """
    # For MVP, this is a simplified check
    # Full implementation would analyze shift gaps for consecutive rest
    weekly_hours = get_weekly_hours(employee_id, week_start)

    # If working more than (168 - required_rest) hours, likely violation
    max_work_hours = 168 - settings.weekly_rest_hours
    if weekly_hours > max_work_hours:
        return ComplianceViolation(
            rule_code="WEEKLY_REST",
            description=f"Weekly hours {weekly_hours:.1f}h may prevent {settings.weekly_rest_hours}h rest",
            severity="WARNING",
        )

    return None


def save_shift(shift: ShiftCreate) -> Optional[Shift]:
    """Persist a shift to the database.

    Args:
        shift: The shift data to save.

    Returns:
        The created Shift with database-generated fields, or None on failure.

    Raises:
        Exception: If database operation fails.
    """
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO shifts (
                    employee_id, start_time, end_time, status,
                    is_clopen_violation, violation_reason, manager_override_reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    str(shift.employee_id),
                    shift.start_time,
                    shift.end_time,
                    shift.status.value,
                    shift.is_clopen_violation,
                    shift.violation_reason,
                    shift.manager_override_reason,
                ),
            )
            result = cur.fetchone()
            if result:
                return Shift(
                    id=UUID(str(result["id"])),
                    created_at=result["created_at"],
                    **shift.model_dump(),
                )
            return None
    except Exception as e:
        logger.error("Failed to save shift: %s", e)
        return None


def generate_draft_schedule(
    start_date: date,
    end_date: date,
) -> list[Shift]:
    """Generate a draft schedule for the specified date range.

    Creates shifts based on requirements while respecting availability
    and flagging compliance violations. Assigns shifts fairly based on
    accumulated hours.

    Args:
        start_date: Start of the scheduling period (inclusive).
        end_date: End of the scheduling period (inclusive).

    Returns:
        List of created Shift objects with compliance flags set.

    Raises:
        ValueError: If date range is invalid.

    Example:
        >>> from datetime import date
        >>> shifts = generate_draft_schedule(
        ...     start_date=date(2024, 1, 15),
        ...     end_date=date(2024, 1, 21),
        ... )
        >>> print(f"Created {len(shifts)} shifts")
    """
    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    # Step 1: Fetch all availability for the date range
    availability_records = get_availability_for_range(start_date, end_date)

    # Index availability by date and shift type
    availability_by_date: dict[date, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"openers": [], "closers": []}
    )

    for record in availability_records:
        shift_date = record["shift_date"]
        if record["can_open"]:
            availability_by_date[shift_date]["openers"].append(record)
        if record["can_close"]:
            availability_by_date[shift_date]["closers"].append(record)

    # Track hours allocated per employee for fairness
    hours_allocated: dict[UUID, float] = defaultdict(float)
    created_shifts: list[Shift] = []

    # Step 2: Iterate through each day in the range
    current_date = start_date
    while current_date <= end_date:
        day_of_week = current_date.weekday()
        requirements = SHIFT_REQUIREMENTS.get(
            day_of_week,
            {"openers": 2, "closers": 2},
        )

        # Get week start for weekly compliance checks
        week_start = current_date - timedelta(days=day_of_week)

        # Process opening shifts
        opening_candidates = availability_by_date[current_date]["openers"]
        opening_shifts = _allocate_shifts(
            candidates=opening_candidates,
            required_count=requirements["openers"],
            shift_date=current_date,
            shift_start_hour=OPENING_SHIFT_START,
            shift_end_hour=OPENING_SHIFT_END,
            hours_allocated=hours_allocated,
            week_start=week_start,
        )
        created_shifts.extend(opening_shifts)

        # Process closing shifts
        closing_candidates = availability_by_date[current_date]["closers"]
        closing_shifts = _allocate_shifts(
            candidates=closing_candidates,
            required_count=requirements["closers"],
            shift_date=current_date,
            shift_start_hour=CLOSING_SHIFT_START,
            shift_end_hour=CLOSING_SHIFT_END,
            hours_allocated=hours_allocated,
            week_start=week_start,
        )
        created_shifts.extend(closing_shifts)

        current_date += timedelta(days=1)

    logger.info(
        "Generated %d draft shifts from %s to %s",
        len(created_shifts),
        start_date,
        end_date,
    )

    return created_shifts


def _allocate_shifts(
    candidates: list[dict[str, Any]],
    required_count: int,
    shift_date: date,
    shift_start_hour: int,
    shift_end_hour: int,
    hours_allocated: dict[UUID, float],
    week_start: date,
) -> list[Shift]:
    """Allocate shifts to candidates with fairness and compliance checks.

    Args:
        candidates: List of available employees.
        required_count: Number of shifts to fill.
        shift_date: The date of the shift.
        shift_start_hour: Shift start hour (0-23).
        shift_end_hour: Shift end hour (0-23).
        hours_allocated: Running tally of hours per employee.
        week_start: Monday of the current week.

    Returns:
        List of created Shift objects.
    """
    created_shifts: list[Shift] = []

    # Sort candidates by hours allocated (fairness - fewest hours first)
    sorted_candidates = sorted(
        candidates,
        key=lambda c: hours_allocated.get(UUID(str(c["employee_id"])), 0),
    )

    # Create timezone-aware datetimes for shift
    shift_start = datetime(
        shift_date.year,
        shift_date.month,
        shift_date.day,
        shift_start_hour,
        0,
        0,
        tzinfo=timezone.utc,
    )
    shift_end = datetime(
        shift_date.year,
        shift_date.month,
        shift_date.day,
        shift_end_hour,
        0,
        0,
        tzinfo=timezone.utc,
    )
    shift_duration = (shift_end - shift_start).total_seconds() / 3600

    assigned_count = 0
    for candidate in sorted_candidates:
        if assigned_count >= required_count:
            break

        employee_id = UUID(str(candidate["employee_id"]))
        max_weekly = candidate.get("max_weekly_hours", settings.max_weekly_hours)

        # Check if employee would exceed weekly hours
        current_weekly = get_weekly_hours(employee_id, week_start)
        if current_weekly + shift_duration > max_weekly:
            logger.debug(
                "Skipping %s: would exceed weekly hours (%s + %s > %s)",
                candidate["full_name"],
                current_weekly,
                shift_duration,
                max_weekly,
            )
            continue

        # Step 4: Compliance checks
        is_violation = False
        violation_reason = None

        # Rule A: Rest period check
        rest_violation = check_rest_period_violation(employee_id, shift_start)
        if rest_violation:
            is_violation = True
            violation_reason = rest_violation.description
            logger.warning(
                "Compliance risk for %s on %s: %s",
                candidate["full_name"],
                shift_date,
                violation_reason,
            )

        # Rule B: Weekly rest check
        weekly_violation = check_weekly_rest_violation(employee_id, week_start)
        if weekly_violation and not violation_reason:
            is_violation = True
            violation_reason = weekly_violation.description

        # Step 5: Create the shift
        shift_data = ShiftCreate(
            employee_id=employee_id,
            start_time=shift_start,
            end_time=shift_end,
            status=ShiftStatus.DRAFT,
            is_clopen_violation=is_violation,
            violation_reason=violation_reason,
        )

        # Step 6: Save to database
        saved_shift = save_shift(shift_data)
        if saved_shift:
            created_shifts.append(saved_shift)
            hours_allocated[employee_id] = (
                hours_allocated.get(employee_id, 0) + shift_duration
            )
            assigned_count += 1
            logger.info(
                "Assigned %s shift on %s to %s",
                "opening" if shift_start_hour < 12 else "closing",
                shift_date,
                candidate["full_name"],
            )

    if assigned_count < required_count:
        logger.warning(
            "Could only fill %d/%d slots for %s on %s",
            assigned_count,
            required_count,
            "opening" if shift_start_hour < 12 else "closing",
            shift_date,
        )

    return created_shifts
