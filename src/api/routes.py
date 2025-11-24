"""API routes for ShiftGuard Flask application.

This module defines the REST API endpoints for availability ingestion,
schedule generation, and calendar publishing.
"""

import logging
import os
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from src.models.schemas import ShiftStatus
from src.services.availability import ingest_availability
from src.services.scheduler import generate_draft_schedule

logger = logging.getLogger(__name__)

# Create Blueprint for API routes
api = Blueprint("api", __name__, url_prefix="/api/v1")


@api.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint.

    Returns:
        JSON response with service status.
    """
    return jsonify({"status": "healthy", "service": "ShiftGuard"}), 200


@api.route("/shifts", methods=["GET"])
def get_shifts():
    """Get shifts with optional filtering.

    Query Parameters:
        start_date: Start date filter (YYYY-MM-DD format, required)
        end_date: End date filter (YYYY-MM-DD format, required)
        status: Optional status filter (DRAFT, AWAITING_RESPONSE, CONFIRMED, DECLINED, PUBLISHED)

    Returns:
        JSON list of shifts with employee information.

    Example request:
        GET /api/v1/shifts?start_date=2025-11-24&end_date=2025-11-30
        GET /api/v1/shifts?start_date=2025-11-24&end_date=2025-11-30&status=DRAFT
    """
    from src.database import get_db_cursor

    # Parse required date params
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    status_filter = request.args.get("status")

    if not start_date_str or not end_date_str:
        return jsonify({
            "error": "Missing required query parameters: start_date, end_date"
        }), 400

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError as e:
        return jsonify({"error": f"Invalid date format: {e}"}), 400

    if start_date > end_date:
        return jsonify({"error": "start_date must be before end_date"}), 400

    # Build query
    try:
        with get_db_cursor(commit=False) as cur:
            if status_filter:
                cur.execute(
                    """
                    SELECT
                        s.id,
                        s.employee_id,
                        e.full_name as employee_name,
                        e.email as employee_email,
                        s.start_time,
                        s.end_time,
                        s.status,
                        s.is_clopen_violation,
                        s.violation_reason,
                        s.created_at
                    FROM shifts s
                    JOIN employees e ON s.employee_id = e.id
                    WHERE DATE(s.start_time) BETWEEN %s AND %s
                      AND s.status = %s
                    ORDER BY s.start_time, e.full_name
                    """,
                    (start_date, end_date, status_filter),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        s.id,
                        s.employee_id,
                        e.full_name as employee_name,
                        e.email as employee_email,
                        s.start_time,
                        s.end_time,
                        s.status,
                        s.is_clopen_violation,
                        s.violation_reason,
                        s.created_at
                    FROM shifts s
                    JOIN employees e ON s.employee_id = e.id
                    WHERE DATE(s.start_time) BETWEEN %s AND %s
                    ORDER BY s.start_time, e.full_name
                    """,
                    (start_date, end_date),
                )

            rows = cur.fetchall()

            shifts = []
            for row in rows:
                shifts.append({
                    "id": str(row["id"]),
                    "employee_id": str(row["employee_id"]),
                    "employee_name": row["employee_name"],
                    "employee_email": row["employee_email"],
                    "start_time": row["start_time"].isoformat() if row["start_time"] else None,
                    "end_time": row["end_time"].isoformat() if row["end_time"] else None,
                    "status": row["status"],
                    "is_violation": row["is_clopen_violation"],
                    "violation_reason": row["violation_reason"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                })

            return jsonify({
                "shifts": shifts,
                "count": len(shifts),
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
            }), 200

    except Exception as e:
        import traceback
        logger.error("Failed to fetch shifts: %s", e)
        return jsonify({
            "error": f"Failed to fetch shifts: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@api.route("/employees", methods=["GET"])
def get_employees():
    """Get all employees with their standard availability.

    Returns:
        JSON list of employees with their weekly availability patterns.

    Example response:
        {
            "employees": [
                {
                    "id": "...",
                    "full_name": "John Doe",
                    "email": "john@example.com",
                    "availability": {
                        "Monday": {"can_open": true, "can_close": false},
                        "Tuesday": {"can_open": true, "can_close": true},
                        ...
                    }
                }
            ]
        }
    """
    from src.database import get_db_cursor

    DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    try:
        with get_db_cursor(commit=False) as cur:
            # Get all active employees
            cur.execute(
                """
                SELECT id, full_name, email, max_weekly_hours, is_active
                FROM employees
                WHERE is_active = TRUE
                ORDER BY full_name
                """
            )
            employee_rows = cur.fetchall()

            # Get all standard availability
            cur.execute(
                """
                SELECT employee_id, day_of_week, can_open, can_close
                FROM standard_availability
                ORDER BY employee_id, day_of_week
                """
            )
            availability_rows = cur.fetchall()

            # Build availability lookup
            availability_map: dict = {}
            for row in availability_rows:
                emp_id = str(row["employee_id"])
                if emp_id not in availability_map:
                    availability_map[emp_id] = {}
                day_name = DAY_NAMES[row["day_of_week"]]
                availability_map[emp_id][day_name] = {
                    "can_open": row["can_open"],
                    "can_close": row["can_close"],
                }

            # Build response
            employees = []
            for row in employee_rows:
                emp_id = str(row["id"])
                employees.append({
                    "id": emp_id,
                    "full_name": row["full_name"],
                    "email": row["email"],
                    "max_weekly_hours": row["max_weekly_hours"],
                    "is_active": row["is_active"],
                    "availability": availability_map.get(emp_id, {}),
                })

            return jsonify({
                "employees": employees,
                "count": len(employees),
            }), 200

    except Exception as e:
        logger.error("Failed to fetch employees: %s", e)
        return jsonify({"error": f"Failed to fetch employees: {str(e)}"}), 500


@api.route("/availability/webhook", methods=["POST"])
def availability_webhook():
    """Webhook endpoint for Google Forms/Apps Script availability submissions.

    Accepts two payload formats:

    Format 1 - Google Apps Script (from Google Forms):
        {
            "email": "john@example.com",
            "answers": {
                "date": "2024-01-15",
                "can_open": "Yes",
                "can_close": "No",
                "notes": "Must leave by 4pm"
            }
        }

    Format 2 - Direct/Batch submission:
        {
            "email": "john@example.com",
            "dates": ["2024-01-15", "2024-01-16"],
            "can_open_dates": ["2024-01-15"],
            "can_close_dates": ["2024-01-16"],
            "notes": {"2024-01-15": "Must leave by 4pm"}
        }

    Returns:
        JSON response indicating success or failure.
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    payload = request.get_json()

    if not payload:
        return jsonify({"error": "Empty payload"}), 400

    logger.info("Received webhook payload: %s", payload)

    # Check if this is recurring availability (has day names in answers)
    # If so, pass directly to ingest_availability which handles it
    answers = payload.get("answers", {})
    day_names = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    has_day_keys = any(key.lower() in day_names for key in answers.keys())

    if has_day_keys:
        # Recurring availability - pass directly to ingest_availability
        logger.info("Detected recurring availability payload")
        success = ingest_availability(payload)
        if success:
            return jsonify({"status": "success", "message": "Availability recorded"}), 200
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to process availability. Employee may not exist.",
            }), 400

    # Detect and transform Google Apps Script format (date-based)
    if "answers" in payload:
        payload = transform_google_apps_script_payload(payload)
        if payload is None:
            return jsonify({
                "status": "error",
                "message": "Invalid Google Apps Script payload format",
            }), 400

    # Convert date strings to date objects
    try:
        if "dates" in payload:
            payload["dates"] = [
                datetime.strptime(d, "%Y-%m-%d").date()
                if isinstance(d, str) else d
                for d in payload["dates"]
            ]
        if "can_open_dates" in payload:
            payload["can_open_dates"] = [
                datetime.strptime(d, "%Y-%m-%d").date()
                if isinstance(d, str) else d
                for d in payload["can_open_dates"]
            ]
        if "can_close_dates" in payload:
            payload["can_close_dates"] = [
                datetime.strptime(d, "%Y-%m-%d").date()
                if isinstance(d, str) else d
                for d in payload["can_close_dates"]
            ]
    except ValueError as e:
        logger.error("Date parsing error: %s", e)
        return jsonify({"error": f"Invalid date format: {e}"}), 400

    success = ingest_availability(payload)

    if success:
        logger.info("Availability processed for %s", payload.get("email"))
        return jsonify({"status": "success", "message": "Availability recorded"}), 200
    else:
        logger.warning("Availability processing failed for %s", payload.get("email"))
        return jsonify({
            "status": "error",
            "message": "Failed to process availability. Employee may not exist.",
        }), 400


def transform_google_apps_script_payload(payload: dict) -> dict | None:
    """Transform Google Apps Script payload to internal format.

    Google Apps Script sends:
        {
            "email": "user@example.com",
            "answers": {
                "date": "2024-01-15",
                "can_open": "Yes",  # or "No"
                "can_close": "Yes", # or "No"
                "notes": "Optional notes"
            }
        }

    We transform to:
        {
            "email": "user@example.com",
            "dates": ["2024-01-15"],
            "can_open_dates": ["2024-01-15"],  # if can_open == "Yes"
            "can_close_dates": [],              # if can_close == "No"
            "notes": {"2024-01-15": "Optional notes"}
        }

    Args:
        payload: The Google Apps Script payload.

    Returns:
        Transformed payload dict, or None if invalid.
    """
    try:
        email = payload.get("email")
        answers = payload.get("answers", {})

        if not email:
            logger.error("Missing email in Google Apps Script payload")
            return None

        # Extract date - support multiple formats
        date_str = answers.get("date") or answers.get("Date")
        if not date_str:
            logger.error("Missing date in Google Apps Script payload")
            return None

        # Parse various date formats
        date_obj = None
        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]:
            try:
                date_obj = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue

        if date_obj is None:
            logger.error("Could not parse date: %s", date_str)
            return None

        date_iso = date_obj.isoformat()

        # Parse can_open/can_close (handle Yes/No/TRUE/FALSE/1/0)
        can_open_raw = str(answers.get("can_open", answers.get("Can Open", "No")))
        can_close_raw = str(answers.get("can_close", answers.get("Can Close", "No")))

        def parse_bool(val: str) -> bool:
            return val.lower() in ("yes", "true", "1", "y")

        can_open = parse_bool(can_open_raw)
        can_close = parse_bool(can_close_raw)

        # Build transformed payload
        transformed = {
            "email": email,
            "dates": [date_iso],
            "can_open_dates": [date_iso] if can_open else [],
            "can_close_dates": [date_iso] if can_close else [],
            "notes": {},
        }

        # Add notes if present
        notes = answers.get("notes") or answers.get("Notes") or answers.get("note")
        if notes:
            transformed["notes"] = {date_iso: notes}

        logger.info("Transformed Google Apps Script payload: %s", transformed)
        return transformed

    except Exception as e:
        logger.error("Failed to transform Google Apps Script payload: %s", e)
        return None


@api.route("/schedule/generate", methods=["POST"])
def generate_schedule():
    """Generate a draft schedule for a date range.

    Expects a JSON payload with:
        - start_date: Start date (YYYY-MM-DD format)
        - end_date: End date (YYYY-MM-DD format)

    Returns:
        JSON response with generated shifts and statistics.

    Example request:
        POST /api/v1/schedule/generate
        Content-Type: application/json
        {
            "start_date": "2024-01-15",
            "end_date": "2024-01-21"
        }
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    payload = request.get_json()

    if not payload:
        return jsonify({"error": "Empty payload"}), 400

    # Validate required fields
    if "start_date" not in payload or "end_date" not in payload:
        return jsonify({
            "error": "Missing required fields: start_date, end_date",
        }), 400

    # Parse dates
    try:
        start_date = datetime.strptime(payload["start_date"], "%Y-%m-%d").date()
        end_date = datetime.strptime(payload["end_date"], "%Y-%m-%d").date()
    except ValueError as e:
        return jsonify({"error": f"Invalid date format: {e}"}), 400

    if start_date > end_date:
        return jsonify({"error": "start_date must be before end_date"}), 400

    # Generate the schedule
    try:
        shifts = generate_draft_schedule(start_date, end_date)

        # Count violations
        violations = sum(1 for s in shifts if s.is_clopen_violation)

        response = {
            "status": "success",
            "shifts_created": len(shifts),
            "violations_flagged": violations,
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "shifts": [
                {
                    "id": str(s.id),
                    "employee_id": str(s.employee_id),
                    "start_time": s.start_time.isoformat(),
                    "end_time": s.end_time.isoformat(),
                    "status": s.status.value,
                    "is_violation": s.is_clopen_violation,
                    "violation_reason": s.violation_reason,
                }
                for s in shifts
            ],
        }

        return jsonify(response), 200

    except Exception as e:
        logger.error("Schedule generation failed: %s", e)
        return jsonify({
            "status": "error",
            "message": f"Schedule generation failed: {str(e)}",
        }), 500


@api.route("/schedule/publish", methods=["POST"])
def publish_schedule():
    """Publish DRAFT shifts to Google Calendar in batches.

    Processes shifts where status='DRAFT' AND is_clopen_violation=False.
    Call repeatedly until 'remaining' is 0 to publish all shifts.

    Accepts optional JSON payload:
        - batch_size: Number of shifts to process per call (default: 5, max: 10)

    Returns:
        JSON response with:
        - published: Shifts published in this batch
        - failed: Shifts that failed in this batch
        - remaining: Shifts still waiting to be published

    Example request:
        POST /api/v1/schedule/publish
        Content-Type: application/json
        {"batch_size": 5}

    Example loop to publish all:
        while True:
            result = POST /api/v1/schedule/publish
            if result['remaining'] == 0:
                break
    """
    # Parse optional batch_size from JSON body
    batch_size = 5  # Default
    if request.is_json:
        payload = request.get_json() or {}
        batch_size = payload.get("batch_size", 5)
        # Clamp batch_size to safe range
        batch_size = max(1, min(10, int(batch_size)))

    logger.info("Publish endpoint called with batch_size=%d", batch_size)

    # Publish to calendar
    try:
        from src.services.calendar import publish_shifts
        result = publish_shifts(batch_size)

        response = {
            "status": "success",
            "published": result["published"],
            "failed": result["failed"],
            "remaining": result["remaining"],
        }

        # Include error message if present
        if "error" in result:
            response["error"] = result["error"]
            response["status"] = "error"

        return jsonify(response), 200

    except Exception as e:
        logger.error("Calendar publish failed: %s", e)
        return jsonify({
            "status": "error",
            "message": f"Calendar publish failed: {str(e)}",
            "published": 0,
            "failed": 0,
            "remaining": 0,
        }), 500


# Create a separate blueprint for cron endpoints (no /api/v1 prefix)
cron_api = Blueprint("cron_api", __name__)


@cron_api.route("/api/cron/generate_schedule", methods=["GET"])
def cron_generate_schedule():
    """Secure cron endpoint for automatic schedule generation.

    Called by Vercel Cron every Friday at 5 PM Pacific Time.
    Generates the draft schedule for the upcoming week (Monday-Sunday).

    Security:
        Requires Authorization header with Bearer token matching CRON_SECRET.

    Returns:
        JSON response with generated shifts summary.
    """
    # Security check
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret:
        auth_header = request.headers.get("Authorization")
        if auth_header != f"Bearer {cron_secret}":
            logger.warning("Unauthorized cron request attempt")
            return jsonify({"error": "Unauthorized"}), 401

    try:
        # Calculate date range for next week (Monday-Sunday)
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7  # Next Monday if today is Monday

        start_date = today + timedelta(days=days_until_monday)
        end_date = start_date + timedelta(days=6)  # Sunday

        logger.info(
            "Cron job triggered: Generating schedule for %s to %s",
            start_date,
            end_date,
        )

        # Generate the schedule
        shifts = generate_draft_schedule(start_date, end_date)

        # Count results
        total_shifts = len(shifts)
        violations = sum(1 for s in shifts if s.is_clopen_violation)

        logger.info(
            "Schedule generated: %d shifts, %d violations",
            total_shifts,
            violations,
        )

        return jsonify({
            "status": "success",
            "message": "Schedule generated successfully",
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "shifts_created": total_shifts,
            "violations_flagged": violations,
        }), 200

    except Exception as e:
        logger.error("Cron job failed: %s", e)
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500
