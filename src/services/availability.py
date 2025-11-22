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


def ingest_availability(payload: dict[str, Any]) -> bool:
    """Process incoming webhook data from Google Forms.

    This function extracts availability information from a Google Forms
    submission and persists it to the database. It validates the employee
    exists before creating availability records.

    Args:
        payload: The raw webhook payload from Google Forms containing:
            - email: The respondent's email address
            - dates: List of dates being submitted
            - can_open_dates: Dates available for opening shifts
            - can_close_dates: Dates available for closing shifts
            - notes: Optional dict mapping dates to notes

    Returns:
        True if all availability records were successfully processed,
        False if the employee was not found or processing failed.

    Raises:
        ValueError: If payload validation fails.

    Example:
        >>> payload = {
        ...     "email": "john@example.com",
        ...     "dates": ["2024-01-15", "2024-01-16"],
        ...     "can_open_dates": ["2024-01-15"],
        ...     "can_close_dates": ["2024-01-16"],
        ...     "notes": {"2024-01-15": "Must leave by 4pm"}
        ... }
        >>> success = ingest_availability(payload)
    """
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
