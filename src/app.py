"""Flask application factory for ShiftGuard.

This module provides the application factory pattern for creating
configured Flask application instances.
"""

import logging
from typing import Optional

from flask import Flask

from src.api.routes import api
from src.config import settings
from src.database import close_db, init_db


def create_app(test_config: Optional[dict] = None) -> Flask:
    """Create and configure the Flask application.

    Uses the application factory pattern to create Flask instances
    with proper configuration for different environments.

    Args:
        test_config: Optional configuration dict for testing.
            Overrides default settings when provided.

    Returns:
        Configured Flask application instance.

    Example:
        >>> app = create_app()
        >>> app.run()

        >>> # For testing
        >>> test_app = create_app({"TESTING": True})
    """
    app = Flask(__name__)

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if settings.flask_debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Load configuration
    app.config.update(
        SECRET_KEY=settings.flask_secret_key,
        ENV=settings.flask_env,
        DEBUG=settings.flask_debug,
    )

    # Apply test configuration if provided
    if test_config:
        app.config.update(test_config)

    # Register blueprints
    app.register_blueprint(api)

    # Initialize database on first request
    @app.before_request
    def before_first_request():
        """Initialize database connection pool before handling requests."""
        if not hasattr(app, "_db_initialized"):
            try:
                init_db()
                app._db_initialized = True
                app.logger.info("Database connection pool initialized")
            except Exception as e:
                app.logger.error("Failed to initialize database: %s", e)
                raise

    # Cleanup on shutdown
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Clean up resources when application context ends."""
        pass  # Connection pool cleanup handled at application shutdown

    # Register root route
    @app.route("/")
    def index():
        """Root endpoint with API information."""
        return {
            "service": "ShiftGuard",
            "version": "0.1.0",
            "description": "Compliant-by-design scheduler for Canadian businesses",
            "endpoints": {
                "health": "/api/v1/health",
                "availability_webhook": "/api/v1/availability/webhook",
                "generate_schedule": "/api/v1/schedule/generate",
                "publish_schedule": "/api/v1/schedule/publish",
            },
        }

    return app


def shutdown_app() -> None:
    """Cleanup function for graceful shutdown.

    Should be called when the application is shutting down
    to properly close database connections.
    """
    close_db()


# Application instance for WSGI servers (Gunicorn, Vercel, etc.)
app = create_app()


if __name__ == "__main__":
    # Development server
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=settings.flask_debug,
    )
