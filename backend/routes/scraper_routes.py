"""
routes/scraper_routes.py — Admin routes for monitoring and triggering Apify scraper.
"""

from flask import Blueprint, jsonify, request, current_app
from tasks.scraper_tasks import run_scraper_pipeline
import threading
import logging

logger = logging.getLogger(__name__)
scraper_bp = Blueprint("scraper", __name__)

# Mock key for demo purposes
ADMIN_KEY = "7f05fe47abfe473393eecc4aa3290347"

@scraper_bp.route("/scrape/start", methods=["GET"])
def trigger_scrape():
    """Manually trigger the Apify scraper pipeline in a background thread."""
    key = request.args.get("key")
    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    # Get the actual app object for the thread
    app = current_app._get_current_object()
    
    # Start the pipeline in the background
    thread = threading.Thread(target=run_scraper_pipeline, args=(app,))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "Apify scraper started in background"}), 200

@scraper_bp.route("/scrape/status", methods=["GET"])
def get_status():
    """Return the status of the scraper."""
    key = request.args.get("key")
    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401
        
    return jsonify({
        "status": "ready",
        "service": "Apify Google Jobs Scraper",
        "last_run": "See logs for details"
    }), 200
