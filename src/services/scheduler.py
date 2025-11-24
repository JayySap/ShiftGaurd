"""Schedule generation service for ShiftGuard.

This module contains the core scheduling logic that generates draft schedules
while respecting labor law compliance requirements (BC/Ontario).
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from src.config import settings, SHIFT_HOURS, DAILY_REQUIREMENTS
from src.database import get_db_cursor
from src.models.schemas import Shift, ShiftCreate, ShiftStatus

logger = logging.getLogger(__name__)


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


def get_standard_availability_for_day(
    day_of_week: int,
) -> list[dict[str, Any]]:
    """Fetch standard availability records for a specific day of week.

    Args:
        day_of_week: Day of week (0=Monday, 6=Sunday).

    Returns:
        List of availability records with employee information.

    Raises:
        Exception: If database query fails.
    """
    with get_db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT
                sa.id,
                sa.employee_id,
                sa.day_of_week,
                sa.can_open,
                sa.can_close,
                e.full_name,
                e.email,
                e.max_weekly_hours,
                e.waived_notice_period
            FROM standard_availability sa
            JOIN employees e ON sa.employee_id = e.id
            WHERE sa.day_of_week = %s
              AND e.is_active = TRUE
            ORDER BY e.full_name
            """,
            (day_of_week,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_availability_for_range(
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Fetch all availability records for a date range.

    This function now queries standard_availability based on the weekday
    of each date in the range, allowing for recurring weekly patterns.

    Args:
        start_date: Start of the date range (inclusive).
        end_date: End of the date range (inclusive).

    Returns:
        List of availability records with employee information and shift_date.

    Raises:
        Exception: If database query fails.
    """
    all_records = []
    current_date = start_date

    while current_date <= end_date:
        # Convert Python weekday (0=Monday, 6=Sunday) to calendar convention (0=Sunday, 1=Monday, ..., 6=Saturday)
        python_weekday = current_date.weekday()  # 0=Monday, 6=Sunday
        calendar_weekday = (python_weekday + 1) % 7  # 0=Sunday, 1=Monday, ..., 6=Saturday

        day_records = get_standard_availability_for_day(calendar_weekday)

        # Add shift_date to each record for compatibility with existing code
        for record in day_records:
            record["shift_date"] = current_date
            all_records.append(record)

        current_date += timedelta(days=1)

    return all_records


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


def categorize_employees(
    availability_records: list[dict[str, Any]],
    shift_date: date,
) -> dict[str, list[dict[str, Any]]]:
    """Categorize employees by their availability type for a given date.

    Categories:
    - OPEN_ONLY: can_open=True, can_close=False
    - CLOSE_ONLY: can_open=False, can_close=True
    - MID_ONLY: can_open=False, can_close=False (interpreted as mid-shift)
    - FLEXIBLE: can_open=True, can_close=True

    Args:
        availability_records: All availability records for the date range.
        shift_date: The specific date to categorize for.

    Returns:
        Dictionary with lists of employees per category.
    """
    categories: dict[str, list[dict[str, Any]]] = {
        "OPEN_ONLY": [],
        "CLOSE_ONLY": [],
        "MID_ONLY": [],
        "FLEXIBLE": [],
    }

    for record in availability_records:
        if record["shift_date"] != shift_date:
            continue

        can_open = record["can_open"]
        can_close = record["can_close"]

        if can_open and can_close:
            categories["FLEXIBLE"].append(record)
        elif can_open and not can_close:
            categories["OPEN_ONLY"].append(record)
        elif not can_open and can_close:
            categories["CLOSE_ONLY"].append(record)
        else:  # not can_open and not can_close
            # Interpret as available for MID shift only
            categories["MID_ONLY"].append(record)

    return categories


def generate_draft_schedule(
    start_date: date,
    end_date: date,
) -> list[Shift]:
    """Generate a draft schedule for the specified date range.

    Uses a 3-shift system (OPEN, MID, CLOSE) with priority-based allocation:
    1. Assign MID_ONLY staff to MID slots first
    2. Assign OPEN_ONLY staff to OPEN slots
    3. Assign CLOSE_ONLY staff to CLOSE slots
    4. Assign FLEXIBLE staff to remaining empty slots

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

    # Track hours allocated per employee for fairness
    hours_allocated: dict[UUID, float] = defaultdict(float)
    created_shifts: list[Shift] = []

    # Track previous day's closing shift assignments for clopen detection
    # Maps employee_id -> end_time of their closing shift
    previous_day_closers: dict[UUID, datetime] = {}

    # Step 2: Iterate through each day in the range
    current_date = start_date
    while current_date <= end_date:
        # Get week start for weekly compliance checks
        day_of_week = current_date.weekday()
        week_start = current_date - timedelta(days=day_of_week)

        # Categorize employees by availability type
        categories = categorize_employees(availability_records, current_date)

        # Track assigned employees for this day to avoid double-booking
        assigned_today: set[UUID] = set()

        # Track filled slots per shift type
        slots_filled: dict[str, int] = {"OPEN": 0, "MID": 0, "CLOSE": 0}

        # Track today's closers for next day's clopen check
        todays_closers: dict[UUID, datetime] = {}

        # Priority 1: Assign MID_ONLY staff to MID slots
        mid_shifts = _allocate_shift_type(
            candidates=categories["MID_ONLY"],
            shift_type="MID",
            required_count=DAILY_REQUIREMENTS["MID"],
            shift_date=current_date,
            hours_allocated=hours_allocated,
            week_start=week_start,
            assigned_today=assigned_today,
            previous_day_closers=previous_day_closers,
            todays_closers=todays_closers,
        )
        created_shifts.extend(mid_shifts)
        slots_filled["MID"] = len(mid_shifts)

        # Priority 2: Assign OPEN_ONLY staff to OPEN slots
        open_shifts = _allocate_shift_type(
            candidates=categories["OPEN_ONLY"],
            shift_type="OPEN",
            required_count=DAILY_REQUIREMENTS["OPEN"],
            shift_date=current_date,
            hours_allocated=hours_allocated,
            week_start=week_start,
            assigned_today=assigned_today,
            previous_day_closers=previous_day_closers,
            todays_closers=todays_closers,
        )
        created_shifts.extend(open_shifts)
        slots_filled["OPEN"] = len(open_shifts)

        # Priority 3: Assign CLOSE_ONLY staff to CLOSE slots
        close_shifts = _allocate_shift_type(
            candidates=categories["CLOSE_ONLY"],
            shift_type="CLOSE",
            required_count=DAILY_REQUIREMENTS["CLOSE"],
            shift_date=current_date,
            hours_allocated=hours_allocated,
            week_start=week_start,
            assigned_today=assigned_today,
            previous_day_closers=previous_day_closers,
            todays_closers=todays_closers,
        )
        created_shifts.extend(close_shifts)
        slots_filled["CLOSE"] = len(close_shifts)

        # Priority 4: Assign FLEXIBLE staff to remaining empty slots
        flexible_candidates = categories["FLEXIBLE"]

        # Fill remaining OPEN slots
        if slots_filled["OPEN"] < DAILY_REQUIREMENTS["OPEN"]:
            remaining_open = DAILY_REQUIREMENTS["OPEN"] - slots_filled["OPEN"]
            extra_open = _allocate_shift_type(
                candidates=flexible_candidates,
                shift_type="OPEN",
                required_count=remaining_open,
                shift_date=current_date,
                hours_allocated=hours_allocated,
                week_start=week_start,
                assigned_today=assigned_today,
                previous_day_closers=previous_day_closers,
                todays_closers=todays_closers,
            )
            created_shifts.extend(extra_open)
            slots_filled["OPEN"] += len(extra_open)

        # Fill remaining MID slots
        if slots_filled["MID"] < DAILY_REQUIREMENTS["MID"]:
            remaining_mid = DAILY_REQUIREMENTS["MID"] - slots_filled["MID"]
            extra_mid = _allocate_shift_type(
                candidates=flexible_candidates,
                shift_type="MID",
                required_count=remaining_mid,
                shift_date=current_date,
                hours_allocated=hours_allocated,
                week_start=week_start,
                assigned_today=assigned_today,
                previous_day_closers=previous_day_closers,
                todays_closers=todays_closers,
            )
            created_shifts.extend(extra_mid)
            slots_filled["MID"] += len(extra_mid)

        # Fill remaining CLOSE slots
        if slots_filled["CLOSE"] < DAILY_REQUIREMENTS["CLOSE"]:
            remaining_close = DAILY_REQUIREMENTS["CLOSE"] - slots_filled["CLOSE"]
            extra_close = _allocate_shift_type(
                candidates=flexible_candidates,
                shift_type="CLOSE",
                required_count=remaining_close,
                shift_date=current_date,
                hours_allocated=hours_allocated,
                week_start=week_start,
                assigned_today=assigned_today,
                previous_day_closers=previous_day_closers,
                todays_closers=todays_closers,
            )
            created_shifts.extend(extra_close)
            slots_filled["CLOSE"] += len(extra_close)

        # Log daily summary
        logger.info(
            "Day %s: OPEN=%d/%d, MID=%d/%d, CLOSE=%d/%d",
            current_date,
            slots_filled["OPEN"], DAILY_REQUIREMENTS["OPEN"],
            slots_filled["MID"], DAILY_REQUIREMENTS["MID"],
            slots_filled["CLOSE"], DAILY_REQUIREMENTS["CLOSE"],
        )

        # Update previous_day_closers for next iteration
        previous_day_closers = todays_closers

        current_date += timedelta(days=1)

    logger.info(
        "Generated %d draft shifts from %s to %s",
        len(created_shifts),
        start_date,
        end_date,
    )

    return created_shifts


def _allocate_shift_type(
    candidates: list[dict[str, Any]],
    shift_type: str,
    required_count: int,
    shift_date: date,
    hours_allocated: dict[UUID, float],
    week_start: date,
    assigned_today: set[UUID],
    previous_day_closers: dict[UUID, datetime],
    todays_closers: dict[UUID, datetime],
) -> list[Shift]:
    """Allocate a specific shift type to candidates.

    Args:
        candidates: List of available employees for this shift type.
        shift_type: One of 'OPEN', 'MID', 'CLOSE'.
        required_count: Number of shifts to fill.
        shift_date: The date of the shift.
        hours_allocated: Running tally of hours per employee.
        week_start: Monday of the current week.
        assigned_today: Set of employee IDs already assigned today.
        previous_day_closers: Dict mapping employee_id to their close shift end time from yesterday.
        todays_closers: Dict to populate with today's close shift assignments.

    Returns:
        List of created Shift objects.
    """
    created_shifts: list[Shift] = []

    # Get shift hours from config
    shift_hours = SHIFT_HOURS[shift_type]
    shift_start_hour = shift_hours["start"]
    shift_end_hour = shift_hours["end"]

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

        # Skip if already assigned today
        if employee_id in assigned_today:
            continue

        max_weekly = candidate.get("max_weekly_hours", settings.max_weekly_hours)

        # Check if employee would exceed weekly hours
        current_weekly = get_weekly_hours(employee_id, week_start)
        if current_weekly + shift_duration > max_weekly:
            logger.debug(
                "Skipping %s for %s: would exceed weekly hours (%s + %s > %s)",
                candidate["full_name"],
                shift_type,
                current_weekly,
                shift_duration,
                max_weekly,
            )
            continue

        # Compliance checks
        is_violation = False
        violation_reason = None

        # Rule A: Clopen check - if assigning OPEN shift, check if they closed yesterday
        if shift_type == "OPEN" and employee_id in previous_day_closers:
            prev_close_end = previous_day_closers[employee_id]
            rest_hours = (shift_start - prev_close_end).total_seconds() / 3600
            if rest_hours < settings.min_rest_hours:
                is_violation = True
                violation_reason = f"Clopen: {rest_hours:.1f}h rest after yesterday's close (< {settings.min_rest_hours}h)"
                logger.warning(
                    "CLOPEN VIOLATION for %s on %s: %s",
                    candidate["full_name"],
                    shift_date,
                    violation_reason,
                )

        # Rule B: Rest period check (from database - previous schedules)
        if not is_violation:
            rest_violation = check_rest_period_violation(employee_id, shift_start)
            if rest_violation:
                is_violation = True
                violation_reason = rest_violation.description
                logger.warning(
                    "Compliance risk for %s on %s %s: %s",
                    candidate["full_name"],
                    shift_date,
                    shift_type,
                    violation_reason,
                )

        # Rule C: Weekly rest check
        if not is_violation:
            weekly_violation = check_weekly_rest_violation(employee_id, week_start)
            if weekly_violation:
                is_violation = True
                violation_reason = weekly_violation.description

        # Create the shift
        shift_data = ShiftCreate(
            employee_id=employee_id,
            start_time=shift_start,
            end_time=shift_end,
            status=ShiftStatus.DRAFT,
            is_clopen_violation=is_violation,
            violation_reason=violation_reason,
        )

        # Save to database
        saved_shift = save_shift(shift_data)
        if saved_shift:
            created_shifts.append(saved_shift)
            hours_allocated[employee_id] = (
                hours_allocated.get(employee_id, 0) + shift_duration
            )
            assigned_today.add(employee_id)
            assigned_count += 1

            # Track closers for next day's clopen check
            if shift_type == "CLOSE":
                todays_closers[employee_id] = shift_end

            logger.info(
                "Assigned %s shift on %s to %s%s",
                shift_type,
                shift_date,
                candidate["full_name"],
                " [VIOLATION]" if is_violation else "",
            )

    if assigned_count < required_count:
        logger.warning(
            "Could only fill %d/%d %s slots on %s",
            assigned_count,
            required_count,
            shift_type,
            shift_date,
        )

    return created_shifts
