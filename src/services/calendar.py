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
from src.models.schemas import ShiftStatus

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
    toolset: Optional[Any] = None,
    connected_account_id: Optional[str] = None,
) -> bool:
    """Create a Google Calendar event for a shift using Composio.

    This function uses the Composio SDK to create calendar events
    and send invitations to employees.

    Args:
        shift: Shift data including start_time, end_time, and employee email.
        toolset: Optional ComposioToolSet instance for dependency injection.
        connected_account_id: Optional Composio connected account ID.

    Returns:
        True if event was created successfully, False otherwise.

    Raises:
        Exception: If calendar API call fails.
    """
    try:
        from composio import ComposioToolSet

        # Initialize toolset if not provided
        if toolset is None or connected_account_id is None:
            # Get connected account for Google Calendar
            toolset = ComposioToolSet()
            connections = toolset.client.connected_accounts.get()
            gcal_connection = next(
                (c for c in connections if c.appName == "googlecalendar" and c.status == "ACTIVE"),
                None
            )
            if gcal_connection:
                connected_account_id = gcal_connection.id
                logger.info("Using Google Calendar connection: %s", connected_account_id)
                # Workaround for SDK bug: bypass check_connected_account validation
                # The SDK's entity.get_connections() returns empty even when connections exist
                toolset.check_connected_account = lambda *args, **kwargs: None
            else:
                logger.error("No active Google Calendar connection found")
                return False

        # Format event details
        event_title = f"ShiftGuard Shift: {shift['full_name']}"
        event_description = (
            "Please Accept/Decline within 24 hours.\n\n"
            f"Employee: {shift['full_name']}\n"
            f"Start: {shift['start_time']}\n"
            f"End: {shift['end_time']}\n\n"
            "Managed by ShiftGuard"
        )

        # Calculate duration
        start_time = shift["start_time"]
        end_time = shift["end_time"]

        # Handle timezone-aware datetimes
        if start_time.tzinfo is not None:
            start_time = start_time.replace(tzinfo=None)
        if end_time.tzinfo is not None:
            end_time = end_time.replace(tzinfo=None)

        duration = end_time - start_time
        duration_hours = int(duration.total_seconds() // 3600)
        duration_minutes = int((duration.total_seconds() % 3600) // 60)

        # Format start_datetime as naive datetime string (YYYY-MM-DDTHH:MM:SS)
        start_datetime_str = start_time.strftime("%Y-%m-%dT%H:%M:%S")

        logger.info(
            "Creating calendar event: %s for %s at %s (duration: %dh %dm)",
            event_title,
            shift["email"],
            start_datetime_str,
            duration_hours,
            duration_minutes,
        )

        # Execute the Composio action
        result = toolset.execute_action(
            action="GOOGLECALENDAR_CREATE_EVENT",
            params={
                "calendar_id": "primary",
                "summary": event_title,
                "description": event_description,
                "start_datetime": start_datetime_str,
                "timezone": settings.default_timezone,
                "event_duration_hour": duration_hours,
                "event_duration_minutes": min(duration_minutes, 59),
                "attendees": [shift["email"]],
                "send_updates": True,
            },
            connected_account_id=connected_account_id,
        )

        # Check result
        if result.get("successful", False):
            logger.info(
                "Successfully created calendar event for %s on %s",
                shift["full_name"],
                shift["start_time"].date() if hasattr(shift["start_time"], 'date') else shift["start_time"],
            )
            return True
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error(
                "Failed to create calendar event for %s: %s",
                shift["full_name"],
                error_msg,
            )
            return False

    except ImportError:
        logger.error("composio-core not installed")
        return False
    except Exception as e:
        logger.error("Calendar event creation failed: %s", e)
        return False


def publish_shifts(
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
        {"sent": int, "errors": int}

    Raises:
        ValueError: If date range is invalid.

    Example:
        >>> from datetime import date
        >>> result = publish_shifts(
        ...     start_date=date(2024, 1, 15),
        ...     end_date=date(2024, 1, 21),
        ... )
        >>> print(f"Sent {result['sent']} invites, {result['errors']} failed")
    """
    if start_date > end_date:
        raise ValueError("start_date must be before or equal to end_date")

    # Step A: Initialize Composio toolset with connection
    try:
        from composio import ComposioToolSet
        toolset = ComposioToolSet()

        # Get connected account for Google Calendar
        connections = toolset.client.connected_accounts.get()
        gcal_connection = next(
            (c for c in connections if c.appName == "googlecalendar" and c.status == "ACTIVE"),
            None
        )
        if not gcal_connection:
            logger.error("No active Google Calendar connection found")
            return {"sent": 0, "errors": 1}

        connected_account_id = gcal_connection.id
        logger.info("Using Google Calendar connection: %s", connected_account_id)

        # Workaround for SDK bug: bypass check_connected_account validation
        toolset.check_connected_account = lambda *a, **kw: None

        logger.info("Composio toolset initialized")
    except Exception as e:
        logger.error("Failed to initialize Composio: %s", e)
        return {"sent": 0, "errors": 1}

    # Step B: Query published shifts
    published_shifts = get_published_shifts(start_date, end_date)

    if not published_shifts:
        logger.info("No published shifts found for %s to %s", start_date, end_date)
        return {"sent": 0, "errors": 0}

    logger.info(
        "Found %d published shifts to send to calendar",
        len(published_shifts),
    )

    # Track results
    sent_count = 0
    error_count = 0

    # Step C & D: Create calendar events for each shift
    for shift in published_shifts:
        shift_id = UUID(str(shift["id"]))

        # Create calendar event via Composio
        if create_calendar_event(shift, toolset, connected_account_id):
            # Update status to AWAITING_RESPONSE
            if update_shift_status(shift_id, ShiftStatus.AWAITING_RESPONSE):
                sent_count += 1
                logger.info(
                    "Shift %s status updated to AWAITING_RESPONSE",
                    shift_id,
                )
            else:
                logger.warning(
                    "Created calendar event but failed to update status for shift %s",
                    shift_id,
                )
                sent_count += 1  # Event was still created
        else:
            error_count += 1

    logger.info(
        "Calendar publish complete: %d sent, %d errors",
        sent_count,
        error_count,
    )

    return {"sent": sent_count, "errors": error_count}


# Keep old function name for backwards compatibility
def publish_to_calendar(
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """Alias for publish_shifts for backwards compatibility.

    Args:
        start_date: Start of the date range (inclusive).
        end_date: End of the date range (inclusive).

    Returns:
        Dictionary with counts: {"sent": int, "failed": int}
    """
    result = publish_shifts(start_date, end_date)
    return {"sent": result["sent"], "failed": result["errors"]}
