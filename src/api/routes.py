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
    """Webhook endpoint for Google Forms availability submissions.

    Expects a JSON payload with:
        - email: Employee's email address
        - dates: List of dates (YYYY-MM-DD format)
        - can_open_dates: List of dates available for opening
        - can_close_dates: List of dates available for closing
        - notes: Optional dict mapping dates to notes

    Returns:
        JSON response indicating success or failure.

    Example request:
        POST /api/v1/availability/webhook
        Content-Type: application/json
        {
            "email": "john@example.com",
            "dates": ["2024-01-15", "2024-01-16"],
            "can_open_dates": ["2024-01-15"],
            "can_close_dates": ["2024-01-16"],
            "notes": {"2024-01-15": "Must leave by 4pm"}
        }
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    payload = request.get_json()

    if not payload:
        return jsonify({"error": "Empty payload"}), 400

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
