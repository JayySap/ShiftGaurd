"""Vercel Cron Job handler for automatic schedule generation.

This endpoint is called by Vercel Cron every Friday at 5 PM Pacific Time.
(Configured as Saturday 1 AM UTC = Friday 5 PM PST)

It generates the draft schedule for the upcoming week.

Schedule: 0 1 * * 6 (Saturday 1 AM UTC = Friday 5 PM Pacific)
"""

import json
import logging
import os
import sys
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler for cron job."""

    def do_GET(self):
        """Handle GET request from Vercel Cron."""
        try:
            # Verify this is a legitimate cron request (optional)
            auth_header = self.headers.get("Authorization")
            cron_secret = os.getenv("CRON_SECRET")

            if cron_secret and auth_header != f"Bearer {cron_secret}":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
                return

            # Import here to avoid cold start issues
            from src.database import init_db, close_db
            from src.services.scheduler import generate_draft_schedule

            # Initialize database
            init_db()

            # Calculate date range for next week
            # Generate for Monday-Sunday of the upcoming week
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

            # Clean up
            close_db()

            # Return success response
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            response = {
                "status": "success",
                "message": "Schedule generated successfully",
                "date_range": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
                "shifts_created": total_shifts,
                "violations_flagged": violations,
            }

            self.wfile.write(json.dumps(response).encode())

        except Exception as e:
            logger.error("Cron job failed: %s", e)

            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            response = {
                "status": "error",
                "message": str(e),
            }

            self.wfile.write(json.dumps(response).encode())
