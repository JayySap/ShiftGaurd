"""Vercel serverless entry point for ShiftGuard Flask application.

This module bridges Vercel Serverless Functions to the Flask application.
Vercel will automatically detect this file and use it to serve HTTP requests.
"""

from src.app import create_app

# Initialize the Flask application
app = create_app()
