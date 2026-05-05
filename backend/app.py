"""
app.py — Flask application factory and entry point.

Registers blueprints, sets up CORS, database, error handlers,
and background scheduler.
"""

import os
import sys
from flask import Flask, jsonify
from flask_cors import CORS

from config import Config


def ensure_playwright_installed():
    """Ensure Playwright Chromium is available at runtime."""
    import subprocess
    import logging
    from playwright.sync_api import sync_playwright
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("Checking Playwright Chromium...")
        with sync_playwright() as p:
            # Try to launch; if it fails, it will raise an exception
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            browser.close()
        logger.info("✅ Playwright ready")
    except Exception:
        logger.info("⚠️ Installing Playwright at runtime (Chromium)...")
        try:
            # Install chromium binary only
            subprocess.run(["playwright", "install", "chromium"], check=True)
            logger.info("✅ Playwright installed successfully at runtime")
        except Exception as e:
            logger.error("❌ Failed to install Playwright at runtime: %s", e)


def create_app() -> Flask:
    """
    Application factory. Creates and configures the Flask app.

    Returns:
        Flask: Configured Flask application instance.
    """
    # Ensure logs directory exists before logger initialises
    Config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Run Playwright check once at startup
    ensure_playwright_installed()

    app = Flask(__name__)

    # -------------------------------------------------------------------------
    # Core Flask settings
    # -------------------------------------------------------------------------
    app.config["SECRET_KEY"] = Config.flask.SECRET_KEY
    app.config["DEBUG"] = Config.flask.DEBUG

    # -------------------------------------------------------------------------
    # SQLAlchemy settings (passed to database_service)
    # -------------------------------------------------------------------------
    app.config["SQLALCHEMY_DATABASE_URI"] = Config.database.URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_POOL_SIZE"] = Config.database.POOL_SIZE

    # -------------------------------------------------------------------------
    # CORS — Allow frontend origin
    # -------------------------------------------------------------------------
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": [Config.flask.FRONTEND_URL, "http://localhost:3000"],
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization", "X-API-Key"],
            }
        },
    )

    # -------------------------------------------------------------------------
    # Initialise extensions
    # -------------------------------------------------------------------------
    from utils.logger import setup_logging
    setup_logging()

    from models.job import db
    db.init_app(app)

    # -------------------------------------------------------------------------
    # Register blueprints (route groups)
    # -------------------------------------------------------------------------
    from routes.jobs_routes import jobs_bp
    from routes.telegram_routes import telegram_bp
    from routes.scraper_routes import scraper_bp

    app.register_blueprint(jobs_bp, url_prefix="/api")
    app.register_blueprint(telegram_bp, url_prefix="/api")
    app.register_blueprint(scraper_bp, url_prefix="/api")

    # -------------------------------------------------------------------------
    # Error handlers — always return JSON
    # -------------------------------------------------------------------------
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad Request", "message": str(e)}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Unauthorized", "message": "Invalid or missing API key"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not Found", "message": str(e)}), 404

    @app.errorhandler(422)
    def unprocessable(e):
        return jsonify({"error": "Unprocessable Entity", "message": str(e)}), 422

    @app.errorhandler(500)
    def internal_error(e):
        import logging
        logging.getLogger(__name__).error("Internal Server Error: %s", e, exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

    # -------------------------------------------------------------------------
    # Health check (public)
    # -------------------------------------------------------------------------
    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "walkins-api"}), 200

    # -------------------------------------------------------------------------
    # Create tables if they don't exist
    # -------------------------------------------------------------------------
    with app.app_context():
        db.create_all()

    # -------------------------------------------------------------------------
    # Start background scheduler (works under gunicorn on Render)
    # Only start in production and if not already running.
    # -------------------------------------------------------------------------
    import os
    if os.environ.get("FLASK_ENV") == "production" or not Config.flask.DEBUG:
        try:
            from services.scheduler_service import JobScheduler
            scheduler = JobScheduler(app)
            scheduler.start()
            app.logger.info("✅ Background scheduler started (scrapes every 4-6 hours)")
        except Exception as exc:
            app.logger.warning("Scheduler failed to start: %s", exc)

    return app


def start_scheduler(app: Flask) -> None:
    """Start the background APScheduler inside the app context."""
    from services.scheduler_service import JobScheduler
    scheduler = JobScheduler(app)
    scheduler.start()
    return scheduler


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    # Validate config before starting
    try:
        Config.validate()
    except EnvironmentError as exc:
        print(f"[FATAL] Configuration error:\n{exc}", file=sys.stderr)
        sys.exit(1)

    flask_app = create_app()

    # Start scheduler in non-debug mode (avoids double-start with reloader)
    scheduler = None
    if not Config.flask.DEBUG:
        scheduler = start_scheduler(flask_app)

    try:
        flask_app.run(
            host="0.0.0.0",
            port=Config.flask.PORT,
            debug=Config.flask.DEBUG,
            use_reloader=False,   # Prevent double-start with APScheduler
        )
    finally:
        if scheduler:
            scheduler.stop()
