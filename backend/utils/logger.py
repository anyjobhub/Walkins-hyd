"""
utils/logger.py — Structured rotating file logger for the entire application.

Usage:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Scraper started")
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging() -> None:
    """
    Configure the root logger.

    Called once at application startup in app.py.
    Sets up:
      - Console handler (colorised in dev mode)
      - Rotating file handler (10 MB × 5 backups)
    """
    from config import Config

    cfg = Config.logging

    # Create logs directory
    log_file = Path(cfg.FILE)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, cfg.LEVEL, logging.INFO)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers (prevents duplicates on hot-reload)
    root.handlers.clear()

    # ── Format ───────────────────────────────────────────────────────────────
    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(level)
    root.addHandler(console_handler)

    # ── Rotating file handler ─────────────────────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        filename=cfg.FILE,
        maxBytes=cfg.MAX_BYTES,
        backupCount=cfg.BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # Silence noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    root.info("Logging initialised | level=%s | file=%s", cfg.LEVEL, cfg.FILE)


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger.

    Args:
        name: Usually __name__ of the calling module.

    Returns:
        logging.Logger instance.
    """
    return logging.getLogger(name)


# ─────────────────────────────────────────────────────────────────────────────
# Convenience logging helpers
# ─────────────────────────────────────────────────────────────────────────────

def log_scraper_start(source: str) -> None:
    logger = get_logger(f"scraper.{source}")
    logger.info("━━━ %s scraper STARTED ━━━", source.upper())


def log_scraper_end(source: str, stats: dict) -> None:
    logger = get_logger(f"scraper.{source}")
    logger.info(
        "━━━ %s scraper FINISHED — found=%d added=%d skipped=%d ━━━",
        source.upper(),
        stats.get("jobs_found", 0),
        stats.get("jobs_added", 0),
        stats.get("jobs_skipped", 0),
    )


def log_error(module: str, error: Exception, context: dict = None) -> None:
    logger = get_logger(module)
    logger.error(
        "ERROR in %s: %s | context=%s", module, error, context or {}, exc_info=True
    )


def log_db_operation(operation: str, status: str, details: str = "") -> None:
    logger = get_logger("database")
    logger.debug("DB [%s] %s — %s", operation.upper(), status, details)
