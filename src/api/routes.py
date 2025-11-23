"""API routes for ShiftGuard Flask application.

This module defines the REST API endpoints for availability ingestion,
schedule generation, and calendar publishing.
"""

import logging
from datetime import date, datetime

from flask import Blueprint, jsonify, request

from src.models.schemas import ShiftStatus
from src.services.availability import ingest_availability
from src.services.calendar import publish_to_calendar
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

    # Detect and transform Google Apps Script format
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
    """Publish approved shifts to Google Calendar.

    Expects a JSON payload with:
        - start_date: Start date (YYYY-MM-DD format)
        - end_date: End date (YYYY-MM-DD format)

    Returns:
        JSON response with publish statistics.

    Example request:
        POST /api/v1/schedule/publish
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

    # Publish to calendar
    try:
        result = publish_to_calendar(start_date, end_date)

        return jsonify({
            "status": "success",
            "sent": result["sent"],
            "failed": result["failed"],
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
        }), 200

    except Exception as e:
        logger.error("Calendar publish failed: %s", e)
        return jsonify({
            "status": "error",
            "message": f"Calendar publish failed: {str(e)}",
        }), 500
