"""
utils/monitoring_service.py — System health and metrics tracking.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Simple in-memory metric store (for lightweight deployments without Redis)
_metrics: dict = {}
_start_time = time.time()


class MonitoringService:
    """Tracks operational metrics and system health."""

    def record_metric(self, name: str, value: float, tags: dict = None) -> None:
        """Record a metric value."""
        _metrics[name] = {
            "value": value,
            "tags": tags or {},
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

    def increment(self, name: str, amount: float = 1) -> None:
        """Increment a counter metric."""
        current = _metrics.get(name, {}).get("value", 0)
        self.record_metric(name, current + amount)

    def get_metric(self, name: str) -> dict:
        """Get a metric by name."""
        return _metrics.get(name, {})

    def get_all_metrics(self) -> dict:
        """Return all tracked metrics."""
        return dict(_metrics)

    def get_health_status(self) -> dict:
        """
        Return a health status object.

        Checks:
          - Database connectivity
          - Uptime
        """
        status = {
            "status": "ok",
            "uptime_seconds": round(time.time() - _start_time, 1),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "components": {},
        }

        # Database check
        try:
            from models.job import db
            db.session.execute(db.text("SELECT 1"))
            status["components"]["database"] = "ok"
        except Exception as exc:
            status["components"]["database"] = f"error: {exc}"
            status["status"] = "degraded"

        return status

    def get_dashboard_stats(self) -> dict:
        """Aggregate metrics for the admin dashboard."""
        try:
            from services.database_service import JobRepository, TelegramUserRepository
            job_stats = JobRepository().get_stats()
            subscriber_count = TelegramUserRepository().get_subscriber_count()
            health = self.get_health_status()

            return {
                **job_stats,
                "subscriber_count": subscriber_count,
                "health": health,
                "metrics": self.get_all_metrics(),
            }
        except Exception as exc:
            logger.error("Error generating dashboard stats: %s", exc)
            return {"error": str(exc)}
