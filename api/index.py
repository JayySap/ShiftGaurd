"""Vercel serverless entry point for ShiftGuard Flask application."""

from flask import Flask, request, Response
import os
import sys

app = Flask(__name__)

# Lazy app creation
_real_app = None

def get_real_app():
    global _real_app
    if _real_app is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from src.app import create_app
        _real_app = create_app()
    return _real_app

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy_all(path):
    """Proxy all requests to the lazily-loaded real app."""
    real_app = get_real_app()

    with real_app.test_request_context(
        path=f"/{path}" if path else "/",
        method=request.method,
        headers=dict(request.headers),
        data=request.get_data(),
        content_type=request.content_type,
        query_string=request.query_string,
    ):
        try:
            # Dispatch to the real app
            rv = real_app.full_dispatch_request()
            response = real_app.make_response(rv)
            return Response(
                response.get_data(),
                status=response.status_code,
                headers=dict(response.headers),
                content_type=response.content_type
            )
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc()}, 500
