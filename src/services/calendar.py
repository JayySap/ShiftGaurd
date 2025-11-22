"""Calendar publishing service for ShiftGuard.

This module handles publishing approved shifts to Google Calendar
using the Composio integration.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

from src.config import settings
from src.database import get_db_cursor
from src.models.schemas import CalendarPublishResult, ShiftStatus

logger = logging.getLogger(__name__)


def get_published_shifts(
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Fetch all shifts marked as PUBLISHED within a date range.

    Args:
        start_date: Start of the date range (inclusive).
        end_date: End of the date range (inclusive).

    Returns:
        List of shift records with employee email addresses.

    Raises:
        Exception: If database query fails.
    """
    # Convert dates to datetime for comparison
    start_datetime = datetime(
        start_date.year, start_date.month, start_date.day,
        0, 0, 0, tzinfo=timezone.utc
    )
    end_datetime = datetime(
        end_date.year, end_date.month, end_date.day,
        23, 59, 59, tzinfo=timezone.utc
    )

    with get_db_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT
                s.id,
                s.employee_id,
                s.start_time,
                s.end_time,
                s.status,
                e.email,
                e.full_name
            FROM shifts s
            JOIN employees e ON s.employee_id = e.id
            WHERE s.status = %s
              AND s.start_time BETWEEN %s AND %s
            ORDER BY s.start_time
            """,
            (ShiftStatus.PUBLISHED.value, start_datetime, end_datetime),
        )
        return [dict(row) for row in cur.fetchall()]


def update_shift_status(
    shift_id: UUID,
    new_status: ShiftStatus,
) -> bool:
    """Update the status of a shift.

    Args:
        shift_id: The UUID of the shift to update.
        new_status: The new status to set.

    Returns:
        True if update was successful, False otherwise.

    Raises:
        Exception: If database operation fails.
    """
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE shifts
                SET status = %s
                WHERE id = %s
                """,
                (new_status.value, str(shift_id)),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("Failed to update shift status: %s", e)
        return False


def create_calendar_event(
    shift: dict[str, Any],
    composio_client: Optional[Any] = None,
) -> bool:
    """Create a Google Calendar event for a shift using Composio.

    This function uses the Composio API to create calendar events
    and send invitations to employees.

    Args:
        shift: Shift data including start_time, end_time, and employee email.
        composio_client: Optional Composio client instance for dependency injection.

    Returns:
        True if event was created successfully, False otherwise.

    Raises:
        Exception: If calendar API call fails.
    """
    if not settings.composio_api_key:
        logger.warning("Composio API key not configured, skipping calendar event")
        return False

    try:
        # Format shift details for calendar
        event_title = f"Shift: {shift['full_name']}"
        event_description = (
            "Please Accept/Decline within 24 hours.\n\n"
            f"Employee: {shift['full_name']}\n"
            f"Start: {shift['start_time']}\n"
            f"End: {shift['end_time']}\n\n"
            "Managed by ShiftGuard"
        )

        # If no client provided, attempt to create one
        if composio_client is None:
            try:
                from composio import ComposioToolSet

                composio_client = ComposioToolSet(api_key=settings.composio_api_key)
            except ImportError:
                logger.error("composio-core not installed")
                return False

        # Call Composio's Google Calendar integration
        # Note: Actual Composio API calls would be structured based on their SDK
        # This is a placeholder for the integration point
        result = composio_client.execute_action(
            action="GOOGLECALENDAR_CREATE_EVENT",
            params={
                "calendar_id": settings.google_calendar_id or "primary",
                "summary": event_title,
                "description": event_description,
                "start": {
                    "dateTime": shift["start_time"].isoformat(),
                    "timeZone": settings.default_timezone,
                },
                "end": {
                    "dateTime": shift["end_time"].isoformat(),
                    "timeZone": settings.default_timezone,
                },
                "attendees": [{"email": shift["email"]}],
                "sendUpdates": "all",
            },
        )

        if result.get("success"):
            logger.info(
                "Created calendar event for %s on %s",
                shift["full_name"],
                shift["start_time"].date(),
            )
            return True
        else:
            logger.error(
                "Failed to create calendar event: %s",
                result.get("error", "Unknown error"),
            )
            return False

    except Exception as e:
        logger.error("Calendar event creation failed: %s", e)
        return False


def publish_to_calendar(
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """Push approved shifts to Google Calendar using Composio.

    Retrieves all PUBLISHED shifts within the date range and creates
    Google Calendar events with employee invitations.

    Args:
        start_date: Start of the date range (inclusive).
        end_date: End of the date range (inclusive).

    Returns:
        Dictionary with counts of successful and failed invitations:
        {"sent": int, "failed": int}

    Raises:
        ValueError: If date range is invalid.

    Example:
        >>> from datetime import date
        >>> result = publish_to_calendar(
        ...     start_date=date(2024, 1, 15),
        ...     end_date=date(2024, 1, 21),
        ... )
        >>> print(f"Sent {result['sent']} invites, {result['failed']} failed")
    """
    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    # Step 1: Query published shifts
    published_shifts = get_published_shifts(start_date, end_date)

    if not published_shifts:
        logger.info("No published shifts found for %s to %s", start_date, end_date)
        return {"sent": 0, "failed": 0}

    logger.info(
        "Found %d published shifts to send to calendar",
        len(published_shifts),
    )

    # Step 2: Create calendar events and track results
    result = CalendarPublishResult(sent=0, failed=0)

    for shift in published_shifts:
        shift_id = UUID(str(shift["id"]))

        # Step 3: Create calendar event via Composio
        if create_calendar_event(shift):
            # Update status to AWAITING_RESPONSE
            if update_shift_status(shift_id, ShiftStatus.AWAITING_RESPONSE):
                result.sent += 1
            else:
                logger.warning(
                    "Created calendar event but failed to update status for shift %s",
                    shift_id,
                )
                result.sent += 1  # Event was created successfully
        else:
            result.failed += 1
            result.errors.append(
                f"Failed to create event for {shift['full_name']} on {shift['start_time']}"
            )

    logger.info(
        "Calendar publish complete: %d sent, %d failed",
        result.sent,
        result.failed,
    )

    return {"sent": result.sent, "failed": result.failed}
