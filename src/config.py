"""Configuration management using pydantic-settings.

This module provides type-safe configuration loading from environment variables
with validation and sensible defaults for the ShiftGuard application.
"""

from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes:
        database_url: PostgreSQL connection string (Neon-compatible).
        flask_secret_key: Secret key for Flask session management.
        flask_env: Flask environment (development/production).
        flask_debug: Enable Flask debug mode.
        composio_api_key: API key for Composio integrations.
        google_calendar_id: Target Google Calendar ID for shift publishing.
        default_timezone: Default timezone for shift calculations.
        min_rest_hours: Minimum hours between shifts (labor law compliance).
        weekly_rest_hours: Minimum consecutive hours off per week.
        max_weekly_hours: Default maximum weekly hours per employee.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database Configuration
    database_url: str = Field(
        ...,
        description="PostgreSQL connection string (e.g., postgres://user:pass@host/db)",
    )

    # Flask Configuration
    flask_secret_key: str = Field(
        default="change-me-in-production",
        description="Secret key for Flask sessions",
    )
    flask_env: str = Field(
        default="development",
        description="Flask environment",
    )
    flask_debug: bool = Field(
        default=False,
        description="Enable Flask debug mode",
    )

    # Composio Integration
    composio_api_key: Optional[str] = Field(
        default=None,
        description="API key for Composio calendar integration",
    )

    # Google Calendar
    google_calendar_id: Optional[str] = Field(
        default=None,
        description="Target Google Calendar ID",
    )

    # Timezone & Compliance
    default_timezone: str = Field(
        default="America/Toronto",
        description="Default timezone for shift calculations",
    )
    min_rest_hours: int = Field(
        default=8,
        ge=0,
        description="Minimum rest hours between shifts (labor law)",
    )
    weekly_rest_hours: int = Field(
        default=32,
        ge=0,
        description="Minimum consecutive hours off per week",
    )
    max_weekly_hours: int = Field(
        default=40,
        ge=1,
        description="Default maximum weekly hours per employee",
    )

    @field_validator("flask_env")
    @classmethod
    def validate_flask_env(cls, v: str) -> str:
        """Validate Flask environment value.

        Args:
            v: The environment value to validate.

        Returns:
            The validated environment string.

        Raises:
            ValueError: If environment is not valid.
        """
        allowed = {"development", "production", "testing"}
        if v.lower() not in allowed:
            raise ValueError(f"flask_env must be one of: {allowed}")
        return v.lower()


# Singleton instance for application-wide configuration
settings = Settings()

# Shift hour definitions for the 4-shift system
# COVER shift overlaps MID to ensure 3-person coverage during peak hours
SHIFT_HOURS = {
    "OPEN": {"start": 6, "end": 14},    # 06:00 - 14:00 (8h)
    "MID": {"start": 10, "end": 18},    # 10:00 - 18:00 (8h)
    "COVER": {"start": 11, "end": 19},  # 11:00 - 19:00 (8h) - Peak coverage
    "CLOSE": {"start": 14, "end": 22},  # 14:00 - 22:00 (8h)
}

# Daily staffing requirements (ensures 3-person overlap during peak 14:00-18:00)
DAILY_REQUIREMENTS = {
    "OPEN": 1,
    "MID": 1,
    "COVER": 1,
    "CLOSE": 1,
}

# Shifts that require a Shift Lead (for role enforcement)
SHIFT_LEAD_REQUIRED = ["OPEN", "CLOSE"]
