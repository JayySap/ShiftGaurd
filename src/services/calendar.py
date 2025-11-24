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


def get_publishable_shifts(batch_size: int = 5) -> tuple[list[dict[str, Any]], int]:
    """Fetch DRAFT shifts without violations, limited by batch size.

    Args:
        batch_size: Maximum number of shifts to fetch (default 5 for Vercel timeout safety).

    Returns:
        Tuple of (shifts_list, total_remaining_count).

    Raises:
        Exception: If database query fails.
    """
    with get_db_cursor(commit=False) as cur:
        # First get total count of publishable shifts
        cur.execute(
            """
            SELECT COUNT(*) as total
            FROM shifts s
            JOIN employees e ON s.employee_id = e.id
            WHERE s.status = %s
              AND s.is_clopen_violation = FALSE
            """,
            (ShiftStatus.DRAFT.value,),
        )
        total_result = cur.fetchone()
        total_remaining = total_result["total"] if total_result else 0

        # Then fetch the batch
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
              AND s.is_clopen_violation = FALSE
            ORDER BY s.start_time
            LIMIT %s
            """,
            (ShiftStatus.DRAFT.value, batch_size),
        )
        shifts = [dict(row) for row in cur.fetchall()]

        return shifts, total_remaining


def publish_shifts(batch_size: int = 5) -> dict[str, Any]:
    """Publish DRAFT shifts to Google Calendar using Composio.

    Processes shifts in batches to prevent Vercel function timeouts.
    Only publishes shifts where status='DRAFT' AND is_clopen_violation=False.

    Args:
        batch_size: Maximum number of shifts to process per call (default 5).

    Returns:
        Dictionary with:
        - published: Number of shifts successfully published in this batch
        - failed: Number of shifts that failed in this batch
        - remaining: Number of shifts still waiting to be published

    Example:
        >>> result = publish_shifts(batch_size=5)
        >>> print(f"Published {result['published']}, remaining: {result['remaining']}")
        >>> # Call repeatedly until remaining == 0
    """
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
            return {"published": 0, "failed": 0, "remaining": 0, "error": "No Google Calendar connection"}

        connected_account_id = gcal_connection.id
        logger.info("Using Google Calendar connection: %s", connected_account_id)

        # MONKEY PATCH: Workaround for Composio SDK bug
        # The SDK's entity.get_connections() returns empty even when connections exist
        # This bypasses the check_connected_account validation
        toolset.check_connected_account = lambda *args, **kwargs: None

        logger.info("Composio toolset initialized with monkey patch")
    except ImportError:
        logger.error("composio-core not installed")
        return {"published": 0, "failed": 0, "remaining": 0, "error": "Composio not installed"}
    except Exception as e:
        logger.error("Failed to initialize Composio: %s", e)
        return {"published": 0, "failed": 0, "remaining": 0, "error": str(e)}

    # Step B: Query publishable shifts (DRAFT + no violations) with batch limit
    shifts, total_remaining = get_publishable_shifts(batch_size)

    if not shifts:
        logger.info("No publishable shifts found")
        return {"published": 0, "failed": 0, "remaining": 0}

    logger.info(
        "Processing batch of %d shifts (%d total remaining)",
        len(shifts),
        total_remaining,
    )

    # Track results
    published_count = 0
    failed_count = 0

    # Step C: Create calendar events for each shift with error boundary
    for shift in shifts:
        shift_id = UUID(str(shift["id"]))

        try:
            # Execute Composio action with error boundary
            result = _create_calendar_event_safe(shift, toolset, connected_account_id)

            if result:
                # Update status to AWAITING_RESPONSE
                if update_shift_status(shift_id, ShiftStatus.AWAITING_RESPONSE):
                    published_count += 1
                    logger.info(
                        "Published shift %s for %s on %s",
                        shift_id,
                        shift["full_name"],
                        shift["start_time"],
                    )
                else:
                    # Event created but status update failed - still count as published
                    published_count += 1
                    logger.warning(
                        "Created event but failed to update status for shift %s",
                        shift_id,
                    )
            else:
                failed_count += 1
                logger.error(
                    "Failed to create calendar event for shift %s (%s)",
                    shift_id,
                    shift["full_name"],
                )

        except Exception as e:
            # Error boundary: log and continue to next shift
            failed_count += 1
            logger.error(
                "Exception publishing shift %s: %s",
                shift_id,
                str(e),
            )
            continue

    # Calculate remaining after this batch
    remaining_after = total_remaining - published_count

    logger.info(
        "Batch complete: %d published, %d failed, %d remaining",
        published_count,
        failed_count,
        remaining_after,
    )

    return {
        "published": published_count,
        "failed": failed_count,
        "remaining": max(0, remaining_after),
    }


def _create_calendar_event_safe(
    shift: dict[str, Any],
    toolset: Any,
    connected_account_id: str,
) -> bool:
    """Create a calendar event with error handling.

    This is a wrapper around the Composio execute_action call with
    proper error boundary to prevent one failure from crashing the batch.

    Args:
        shift: Shift data including start_time, end_time, and employee email.
        toolset: Initialized ComposioToolSet instance.
        connected_account_id: Composio connected account ID.

    Returns:
        True if event was created successfully, False otherwise.
    """
    try:
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

        # Format start_datetime as naive datetime string
        start_datetime_str = start_time.strftime("%Y-%m-%dT%H:%M:%S")

        logger.info(
            "Creating event: %s for %s at %s",
            event_title,
            shift["email"],
            start_datetime_str,
        )

        # Execute the Composio action with error boundary
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
            logger.info("Successfully created calendar event for %s", shift["full_name"])
            return True
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Composio returned error: %s", error_msg)
            return False

    except Exception as e:
        logger.error("Exception in _create_calendar_event_safe: %s", e)
        return False


# Keep old function name for backwards compatibility
def publish_to_calendar(batch_size: int = 5) -> dict[str, int]:
    """Alias for publish_shifts for backwards compatibility.

    Args:
        batch_size: Maximum number of shifts to process per call.

    Returns:
        Dictionary with counts: {"sent": int, "failed": int, "remaining": int}
    """
    result = publish_shifts(batch_size)
    return {
        "sent": result["published"],
        "failed": result["failed"],
        "remaining": result["remaining"],
    }
