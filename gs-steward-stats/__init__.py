"""#gs-steward-stats: administrative actions by stewards and global sysops.
"""

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from . import api, auth, pages
from .settings import login_configured, settings


def create_app():
    app = Flask(__name__)
    app.secret_key = settings["secret_key"] or None
    app.config.update(
        SESSION_COOKIE_SECURE=bool(settings["session_cookie_secure"]),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if not login_configured(settings):
        app.logger.warning("Login is not configured: set secret_key, consumer_key and consumer_secret in config.toml")

    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(pages.bp)
    app.before_request(auth.require_login)

    @app.errorhandler(Exception)
    def on_error(e):
        """API errors come back as JSON; everything else keeps Flask's default handling."""
        if request.path.startswith("/api/"):
            code = e.code if isinstance(e, HTTPException) else 500
            if code == 500:
                app.logger.exception("API error")
            return jsonify({"error": str(e)}), code
        if isinstance(e, HTTPException):
            return e
        raise e

    @app.after_request
    def no_store(resp):
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # Steward-specific endpoints (separate module, optional)
    try:
        import steward_live
    except ImportError:
        steward_live = None
    if steward_live:
        from .cache import cached
        from .helpers import force_refresh
        from .wiki_config import load_config
        steward_live.register(app, cached, load_config, force_refresh)

    return app
