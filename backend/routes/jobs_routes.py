"""
routes/jobs_routes.py — REST API endpoints for job data.

Endpoints:
  GET /api/jobs           — List jobs with filters + pagination
  GET /api/jobs/:id       — Single job detail
  GET /api/jobs/search    — Full-text search
  GET /api/jobs/walkin    — Walk-in jobs only
  GET /api/stats          — System statistics
"""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request, g

from services.database_service import JobRepository

logger = logging.getLogger(__name__)
jobs_bp = Blueprint("jobs", __name__)


def get_repo() -> JobRepository:
    """Return a per-request JobRepository (requires app context)."""
    if "repo" not in g:
        g.repo = JobRepository()
    return g.repo


def _parse_bool(val: str) -> bool:
    return str(val).lower() in ("1", "true", "yes")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/jobs — List with filters
# ─────────────────────────────────────────────────────────────────────────────
@jobs_bp.route("/jobs", methods=["GET"])
def get_jobs():
    """
    Get paginated, filtered job listings.

    Query params:
      location          (str)   — City or region
      company           (str)   — Company name substring
      salary_min        (int)   — Min salary in INR
      salary_max        (int)   — Max salary in INR
      experience_level  (str)   — fresher/junior/mid/senior
      walkin_only       (bool)  — Only walk-in jobs
      fresher_friendly  (bool)  — Only fresher-friendly
      source            (str)   — naukri/linkedin/indeed
      page              (int)   — Page number (default 1)
      limit             (int)   — Items per page (max 50, default 20)
    """
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(50, max(1, int(request.args.get("limit", 20))))

        salary_min_raw = request.args.get("salary_min")
        salary_max_raw = request.args.get("salary_max")

        result = get_repo().get_jobs_by_filter(
            location=request.args.get("location"),
            company=request.args.get("company"),
            walkin_only=_parse_bool(request.args.get("walkin_only", False)),
            fresher_friendly=_parse_bool(request.args.get("fresher_friendly", False)),
            salary_min=int(salary_min_raw) if salary_min_raw else None,
            salary_max=int(salary_max_raw) if salary_max_raw else None,
            experience_level=request.args.get("experience_level"),
            source=request.args.get("source"),
            page=page,
            limit=limit,
        )
        return jsonify(result), 200

    except ValueError as e:
        return jsonify({"error": "Invalid parameter", "message": str(e)}), 400
    except Exception as e:
        logger.error("Error in GET /api/jobs: %s", e, exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/jobs/search — Keyword search
# ─────────────────────────────────────────────────────────────────────────────
@jobs_bp.route("/jobs/search", methods=["GET"])
def search_jobs():
    """
    Search jobs by keyword.

    Query params:
      q     (str, required) — Search keyword
      page  (int)
      limit (int)
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(50, max(1, int(request.args.get("limit", 20))))

        result = get_repo().get_jobs_by_filter(
            search_query=q,
            page=page,
            limit=limit,
        )
        result["query"] = q
        return jsonify(result), 200

    except Exception as e:
        logger.error("Error in GET /api/jobs/search: %s", e, exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/jobs/walkin — Walk-in jobs shortcut
# ─────────────────────────────────────────────────────────────────────────────
@jobs_bp.route("/jobs/walkin", methods=["GET"])
def get_walkin_jobs():
    """
    Get walk-in jobs, optionally filtered by location.

    Query params:
      location (str) — City filter
      limit    (int) — Max results (default 50)
    """
    try:
        location = request.args.get("location", "")
        limit = min(100, max(1, int(request.args.get("limit", 50))))
        jobs = get_repo().get_walkin_jobs(location=location, limit=limit)
        return jsonify({"jobs": jobs, "total": len(jobs), "location": location}), 200
    except Exception as e:
        logger.error("Error in GET /api/jobs/walkin: %s", e, exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/jobs/<id> — Single job detail
# ─────────────────────────────────────────────────────────────────────────────
@jobs_bp.route("/jobs/<int:job_id>", methods=["GET"])
def get_job(job_id: int):
    """Get full details for a single job by ID."""
    try:
        job = get_repo().get_job_by_id(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(job), 200
    except Exception as e:
        logger.error("Error in GET /api/jobs/%d: %s", job_id, e, exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/stats — System statistics
# ─────────────────────────────────────────────────────────────────────────────
@jobs_bp.route("/stats", methods=["GET"])
def get_stats():
    """Return aggregated system statistics."""
    try:
        stats = get_repo().get_stats()
        return jsonify(stats), 200
    except Exception as e:
        logger.error("Error in GET /api/stats: %s", e, exc_info=True)
        return jsonify({"error": "Internal server error"}), 500
