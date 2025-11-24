"""Availability ingestion service for ShiftGuard.

This module handles processing incoming availability data from Google Forms
webhooks and persisting it to the database.
"""

import logging
from typing import Any, Optional
from uuid import UUID

from src.database import get_db_cursor
from src.models.schemas import GoogleFormPayload

logger = logging.getLogger(__name__)

# Day name to day_of_week mapping (0=Sunday, 1=Monday, ..., 6=Saturday)
# This matches standard calendar convention
DAY_NAME_TO_NUMBER = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}


def get_employee_id_by_email(email: str) -> Optional[UUID]:
    """Look up an employee's UUID by their email address.

    Args:
        email: The employee's email address to search for.

    Returns:
        The employee's UUID if found, None otherwise.

    Raises:
        Exception: If database query fails.
    """
    with get_db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT id FROM employees
            WHERE email = %s AND is_active = TRUE
            """,
            (email,),
        )
        result = cur.fetchone()
        return UUID(str(result["id"])) if result else None


def upsert_availability(
    employee_id: UUID,
    shift_date: Any,
    can_open: bool,
    can_close: bool,
    note: Optional[str] = None,
) -> bool:
    """Insert or update availability for an employee on a specific date.

    Performs an UPSERT operation to ensure the latest submission is the
    source of truth. If availability already exists for the employee/date
    combination, it will be updated.

    Args:
        employee_id: The UUID of the employee.
        shift_date: The date for this availability.
        can_open: Whether the employee can work opening shifts.
        can_close: Whether the employee can work closing shifts.
        note: Optional notes or constraints.

    Returns:
        True if the upsert was successful, False otherwise.

    Raises:
        Exception: If database operation fails.
    """
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO availability (employee_id, shift_date, can_open, can_close, note)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (employee_id, shift_date)
                DO UPDATE SET
                    can_open = EXCLUDED.can_open,
                    can_close = EXCLUDED.can_close,
                    note = EXCLUDED.note,
                    submitted_at = CURRENT_TIMESTAMP
                """,
                (str(employee_id), shift_date, can_open, can_close, note),
            )
            return True
    except Exception as e:
        logger.error("Failed to upsert availability: %s", e)
        return False


def upsert_standard_availability(
    employee_id: UUID,
    day_of_week: int,
    can_open: bool,
    can_close: bool,
) -> bool:
    """Insert or update standard weekly availability for an employee.

    Args:
        employee_id: The UUID of the employee.
        day_of_week: Day of week (0=Monday, 6=Sunday).
        can_open: Whether the employee can work opening shifts.
        can_close: Whether the employee can work closing shifts.

    Returns:
        True if the upsert was successful, False otherwise.
    """
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO standard_availability (employee_id, day_of_week, can_open, can_close)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (employee_id, day_of_week)
                DO UPDATE SET
                    can_open = EXCLUDED.can_open,
                    can_close = EXCLUDED.can_close,
                    updated_at = NOW()
                """,
                (str(employee_id), day_of_week, can_open, can_close),
            )
            return True
    except Exception as e:
        logger.error("Failed to upsert standard availability: %s", e)
        return False


def parse_shift_options(options: list[str]) -> tuple[bool, bool]:
    """Parse shift options from a list of strings.

    Handles formats like:
    - ['6:00 AM - 2:00 PM', '2:00 PM - 10:00 PM']  (time ranges)
    - ['Can Open (6am)', 'Can Close (10pm)']
    - ['Can Open', 'Can Close']
    - ['open', 'close']

    Time-based logic:
    - If '6:00 AM' or '6am' in values -> can_open = True (OPEN shift)
    - If '2:00 PM - 10:00 PM' or '10pm' or 'close' -> can_close = True (CLOSE shift)
    - If '10:00 AM' -> MID shift (both False, handled by scheduler)

    Args:
        options: List of option strings from form submission.

    Returns:
        Tuple of (can_open, can_close) booleans.
    """
    can_open = False
    can_close = False

    for option in options:
        option_lower = option.lower()

        # Check for time-based patterns
        # OPEN shift: 6:00 AM - 2:00 PM
        if "6:00 am" in option_lower or "6am" in option_lower or "6:00am" in option_lower:
            can_open = True
        if "open" in option_lower:
            can_open = True

        # CLOSE shift: 2:00 PM - 10:00 PM
        if "10:00 pm" in option_lower or "10pm" in option_lower or "10:00pm" in option_lower:
            can_close = True
        if "close" in option_lower:
            can_close = True

        # Check for shift time ranges
        if "2:00 pm - 10:00 pm" in option_lower or "2pm - 10pm" in option_lower:
            can_close = True
        if "6:00 am - 2:00 pm" in option_lower or "6am - 2pm" in option_lower:
            can_open = True

    return can_open, can_close


def ingest_recurring_availability(payload: dict[str, Any]) -> bool:
    """Process recurring weekly availability from Google Forms.

    Handles payload with day-based keys:
    {
        "email": "john@example.com",
        "answers": {
            "Monday": ["Can Open (6am)", "Can Close (10pm)"],
            "Tuesday": ["Can Open (6am)"],
            "Wednesday": [],
            ...
        }
    }

    Args:
        payload: The webhook payload with day-based availability.

    Returns:
        True if processing succeeded, False otherwise.
    """
    email = payload.get("email")
    answers = payload.get("answers", {})

    if not email:
        logger.error("Missing email in recurring availability payload")
        return False

    # Look up employee
    employee_id = get_employee_id_by_email(email)
    if employee_id is None:
        logger.error("Employee not found for email: %s", email)
        return False

    success_count = 0
    total_days = 0

    # Process each day of the week
    for day_name, day_num in DAY_NAME_TO_NUMBER.items():
        # Check for day key in answers (case-insensitive)
        day_options = None
        for key in answers:
            if key.lower() == day_name:
                day_options = answers[key]
                break

        if day_options is None:
            # Day not in payload, skip
            continue

        total_days += 1

        # Parse options list
        if isinstance(day_options, list):
            can_open, can_close = parse_shift_options(day_options)
        elif isinstance(day_options, str):
            # Handle single string value
            can_open, can_close = parse_shift_options([day_options])
        else:
            can_open, can_close = False, False

        # Upsert to standard_availability
        if upsert_standard_availability(
            employee_id=employee_id,
            day_of_week=day_num,
            can_open=can_open,
            can_close=can_close,
        ):
            success_count += 1
            logger.info(
                "Upserted standard availability for %s on %s (open=%s, close=%s)",
                email,
                day_name.capitalize(),
                can_open,
                can_close,
            )
        else:
            logger.warning(
                "Failed to upsert standard availability for %s on %s",
                email,
                day_name.capitalize(),
            )

    if total_days == 0:
        logger.warning("No day keys found in payload for %s", email)
        return False

    logger.info(
        "Processed %d/%d days for recurring availability for %s",
        success_count,
        total_days,
        email,
    )

    return success_count == total_days


def ingest_availability(payload: dict[str, Any]) -> bool:
    """Process incoming webhook data from Google Forms.

    This function detects the payload format and routes to the appropriate
    handler:
    - Recurring availability (day-based keys like Monday, Tuesday, etc.)
    - Specific date availability (dates list)

    Args:
        payload: The raw webhook payload from Google Forms.

    Returns:
        True if all availability records were successfully processed,
        False if the employee was not found or processing failed.
    """
    # Check if this is recurring availability (has day names in answers)
    answers = payload.get("answers", {})
    has_day_keys = any(
        key.lower() in DAY_NAME_TO_NUMBER
        for key in answers.keys()
    )

    if has_day_keys:
        logger.info("Detected recurring availability payload")
        return ingest_recurring_availability(payload)

    # Otherwise, process as specific date availability
    logger.info("Detected specific date availability payload")

    # Validate payload structure
    try:
        form_data = GoogleFormPayload(**payload)
    except Exception as e:
        logger.error("Invalid payload format: %s", e)
        return False

    # Step 1: Look up employee by email
    employee_id = get_employee_id_by_email(form_data.email)

    if employee_id is None:
        logger.error(
            "Employee not found for email: %s. Not creating phantom employee.",
            form_data.email,
        )
        return False

    # Step 2: Process each date's availability
    success_count = 0
    for shift_date in form_data.dates:
        can_open = shift_date in form_data.can_open_dates
        can_close = shift_date in form_data.can_close_dates
        note = form_data.notes.get(str(shift_date))

        if upsert_availability(
            employee_id=employee_id,
            shift_date=shift_date,
            can_open=can_open,
            can_close=can_close,
            note=note,
        ):
            success_count += 1
            logger.info(
                "Upserted availability for %s on %s",
                form_data.email,
                shift_date,
            )
        else:
            logger.warning(
                "Failed to upsert availability for %s on %s",
                form_data.email,
                shift_date,
            )

    total_dates = len(form_data.dates)
    if success_count == total_dates:
        logger.info(
            "Successfully processed all %d availability records for %s",
            total_dates,
            form_data.email,
        )
        return True
    else:
        logger.warning(
            "Processed %d/%d availability records for %s",
            success_count,
            total_dates,
            form_data.email,
        )
        return False
