"""
routes/scraper_routes.py — Admin-only scraper management endpoints.

All routes require the X-API-Key header matching ADMIN_API_KEY in .env.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, jsonify, request, Response

from config import Config
from services.database_service import ScrapLogRepository

logger = logging.getLogger(__name__)
scraper_bp = Blueprint("scraper", __name__)
log_repo = ScrapLogRepository()

_scraper_status = {
    "running": False,
    "last_run": None,
    "last_source": None,
    "next_run": None,
}


# ─────────────────────────────────────────────────────────────────────────────
# Auth middleware
# ─────────────────────────────────────────────────────────────────────────────
def require_admin_key(f):
    """Decorator: reject requests without a valid X-API-Key header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-API-Key", "")
        if not Config.flask.ADMIN_API_KEY or api_key != Config.flask.ADMIN_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/scraper/trigger — Manually trigger scraping
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scraper/trigger", methods=["POST"])
@require_admin_key
def trigger_scraper():
    """
    Trigger scraping for one or more sources.

    Body (JSON):
      sources (list) — e.g. ["naukri", "linkedin", "indeed"]
      location (str) — default "India"
    """
    if _scraper_status["running"]:
        return jsonify({
            "status": "already_running",
            "message": "A scrape is already in progress",
        }), 409

    data = request.get_json(silent=True) or {}
    sources = data.get("sources", ["naukri", "linkedin", "indeed"])
    location = data.get("location", "India")

    valid_sources = {"naukri", "linkedin", "indeed"}
    sources = [s for s in sources if s in valid_sources]

    if not sources:
        return jsonify({"error": "No valid sources specified"}), 400

    # Run scraping in background thread so request returns immediately
    def run_scrape():
        from tasks.scraper_tasks import run_scraper_pipeline
        _scraper_status["running"] = True
        _scraper_status["last_run"] = datetime.now(timezone.utc).isoformat()
        try:
            result = run_scraper_pipeline(sources=sources, location=location)
            _scraper_status["last_result"] = result
        finally:
            _scraper_status["running"] = False

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()

    return jsonify({
        "status": "started",
        "sources": sources,
        "location": location,
        "message": "Scraping started in background. Check /api/scraper/status for updates.",
    }), 202


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/scraper/status — Current scraper status
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scraper/status", methods=["GET"])
@require_admin_key
def scraper_status():
    """Return the current scraper status."""
    return jsonify(_scraper_status), 200


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/scraper/logs — Recent scrape logs
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scraper/logs", methods=["GET"])
@require_admin_key
def scraper_logs():
    """Get recent scraping audit logs."""
    try:
        limit = min(100, max(1, int(request.args.get("limit", 20))))
        logs = log_repo.get_recent_logs(limit=limit)
        return jsonify({"logs": logs, "total": len(logs)}), 200
    except Exception as e:
        logger.error("Error fetching scraper logs: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/scraper/post-to-telegram — Trigger Telegram posting
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scraper/post-to-telegram", methods=["POST"])
@require_admin_key
def post_to_telegram():
    """Manually trigger posting of unposted jobs to Telegram."""
    try:
        from tasks.scraper_tasks import post_unposted_jobs
        result = post_unposted_jobs()
        return jsonify(result), 200
    except Exception as e:
        logger.error("Error posting to Telegram: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/admin/dashboard — Unified admin dashboard data
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/admin/dashboard", methods=["GET"])
@require_admin_key
def admin_dashboard():
    """Return all stats for the admin dashboard."""
    try:
        from services.database_service import JobRepository, TelegramUserRepository
        from utils.monitoring_service import MonitoringService

        stats = JobRepository().get_stats()
        stats["subscriber_count"] = TelegramUserRepository().get_subscriber_count()
        stats["scraper_status"] = _scraper_status
        stats["recent_logs"] = log_repo.get_recent_logs(limit=5)
        stats["health"] = MonitoringService().get_health_status()

        return jsonify(stats), 200
    except Exception as e:
        logger.error("Error fetching dashboard: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /scrape-now — Browser-friendly manual scrape trigger
# Open this URL in your browser to manually scrape all sources.
# Does NOT disturb the automatic scheduler.
# Usage: https://walkins-hyd.onrender.com/scrape-now?key=YOUR_ADMIN_API_KEY
# ─────────────────────────────────────────────────────────────────────────────
@scraper_bp.route("/scrape-now", methods=["GET"])
def scrape_now():
    """
    Browser-friendly scrape trigger. Opens a nice HTML page showing status.
    Protected by ?key= query param (same as ADMIN_API_KEY).
    Runs in background thread — does NOT interfere with scheduled jobs.
    """
    key = request.args.get("key", "")
    if not Config.flask.ADMIN_API_KEY or key != Config.flask.ADMIN_API_KEY:
        return Response("""
        <html><body style="font-family:sans-serif;text-align:center;padding:4rem;background:#111;color:#fff">
        <h1 style="color:#ef4444">❌ Unauthorized</h1>
        <p>Missing or wrong ?key= parameter.</p>
        </body></html>
        """, status=401, mimetype="text/html")

    if _scraper_status.get("running"):
        return Response(f"""
        <html><head><meta http-equiv="refresh" content="10"></head>
        <body style="font-family:sans-serif;text-align:center;padding:4rem;background:#111;color:#fff">
        <h1 style="color:#f59e0b">⏳ Already Running</h1>
        <p>A scrape is already in progress. Page refreshes in 10 seconds...</p>
        <p style="color:#6b7280;font-size:0.85rem">Started: {_scraper_status.get('last_run', 'unknown')}</p>
        </body></html>
        """, status=200, mimetype="text/html")

    # Fire in background thread — scheduler jobs are completely unaffected
    def run_all():
        from tasks.scraper_tasks import run_scraper_pipeline, post_unposted_jobs, run_deduplication
        _scraper_status["running"] = True
        _scraper_status["last_run"] = datetime.now(timezone.utc).isoformat()
        _scraper_status["last_source"] = "manual"
        try:
            logger.info("Manual scrape triggered via /scrape-now")
            result = run_scraper_pipeline(sources=["naukri", "linkedin", "indeed"])
            post_unposted_jobs()
            run_deduplication()
            _scraper_status["last_result"] = result
            logger.info("Manual scrape complete: %s", result)
        except Exception as exc:
            logger.error("Manual scrape error: %s", exc, exc_info=True)
        finally:
            _scraper_status["running"] = False

    thread = threading.Thread(target=run_all, daemon=True)
    thread.start()

    return Response(f"""
    <html>
    <head>
        <meta http-equiv="refresh" content="30;url=/scrape-now?key={key}">
        <title>Scraping Started ✅</title>
    </head>
    <body style="font-family:sans-serif;text-align:center;padding:4rem;background:#0f172a;color:#f1f5f9">
        <div style="max-width:500px;margin:0 auto;background:#1e293b;padding:3rem;border-radius:16px;border:1px solid #334155">
            <div style="font-size:4rem">🚀</div>
            <h1 style="color:#22c55e;margin:1rem 0">Scraping Started!</h1>
            <p style="color:#94a3b8">Running: Naukri + LinkedIn + Indeed</p>
            <p style="color:#94a3b8">After scraping: Posts to Telegram + Removes duplicates</p>
            <hr style="border-color:#334155;margin:2rem 0">
            <p style="color:#64748b;font-size:0.85rem">⏰ Scheduled jobs are NOT affected</p>
            <p style="color:#64748b;font-size:0.85rem">This page auto-refreshes in 30 seconds</p>
            <p style="color:#64748b;font-size:0.8rem;margin-top:2rem">Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <a href="/api/stats" style="display:inline-block;margin-top:1.5rem;padding:10px 24px;background:#7c3aed;color:#fff;text-decoration:none;border-radius:8px;font-weight:600">
                Check Stats →
            </a>
        </div>
    </body>
    </html>
    """, status=202, mimetype="text/html")
