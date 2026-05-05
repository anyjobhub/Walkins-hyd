"""
config.py — Central configuration for the Walk-in Jobs Aggregation System.

Loads environment variables from .env and provides a typed Config object
used throughout the application.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Locate and load the .env file (works for both local dev and production)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get_env(key: str, default=None, required: bool = False):
    """Fetch an env var, optionally raising if missing and required."""
    value = os.environ.get(key, default)
    if required and value is None:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"Check your .env file."
        )
    return value


class DatabaseConfig:
    """PostgreSQL connection and pool settings."""
    URL: str = _get_env("DATABASE_URL", required=True)
    POOL_SIZE: int = int(_get_env("DATABASE_POOL_SIZE", 10))
    MAX_OVERFLOW: int = int(_get_env("DATABASE_MAX_OVERFLOW", 20))
    ECHO: bool = _get_env("DATABASE_ECHO", "false").lower() == "true"


class TelegramConfig:
    """Telegram Bot API settings."""
    BOT_TOKEN: str = _get_env("TELEGRAM_BOT_TOKEN", "")
    CHANNEL_ID: str = _get_env("TELEGRAM_CHANNEL_ID", "")
    ADMIN_CHAT_ID: str = _get_env("TELEGRAM_ADMIN_CHAT_ID", "")
    # Max Telegram message length (4096 chars limit)
    MAX_MESSAGE_LENGTH: int = 4096


class FlaskConfig:
    """Flask application settings."""
    SECRET_KEY: str = _get_env("SECRET_KEY", "dev-secret-change-me-in-production")
    DEBUG: bool = _get_env("FLASK_DEBUG", "false").lower() == "true"
    ENV: str = _get_env("FLASK_ENV", "production")
    PORT: int = int(_get_env("SERVER_PORT", 5000))
    ADMIN_API_KEY: str = _get_env("ADMIN_API_KEY", "")
    FRONTEND_URL: str = _get_env("FRONTEND_URL", "http://localhost:3000")


class LoggingConfig:
    """Logging settings."""
    LEVEL: str = _get_env("LOG_LEVEL", "INFO").upper()
    FILE: str = _get_env("LOG_FILE", "logs/app.log")
    MAX_BYTES: int = int(_get_env("LOG_MAX_BYTES", 10 * 1024 * 1024))  # 10 MB
    BACKUP_COUNT: int = int(_get_env("LOG_BACKUP_COUNT", 5))


class ScraperConfig:
    """Web scraper behaviour settings."""
    DELAY_MIN: float = float(_get_env("SCRAPER_DELAY_MIN", 2))
    DELAY_MAX: float = float(_get_env("SCRAPER_DELAY_MAX", 4))
    MAX_RETRIES: int = int(_get_env("MAX_RETRIES", 3))
    REQUEST_TIMEOUT: int = int(_get_env("REQUEST_TIMEOUT", 30))
    ROTATE_USER_AGENTS: bool = (
        _get_env("USER_AGENTS_ROTATE", "true").lower() == "true"
    )

    # Pool of realistic desktop User-Agents
    USER_AGENTS: list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
        "Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) "
        "Gecko/20100101 Firefox/125.0",
    ]

    # Common headers to appear as a real browser
    DEFAULT_HEADERS: dict = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    }

    # Walk-in keywords used to detect walk-in jobs
    WALKIN_KEYWORDS: list = [
        "walk-in", "walkin", "walk in", "walk-in interview",
        "direct interview", "spot interview", "on-spot interview",
        "open interview", "open house interview",
    ]

    # Keywords that suggest fresher-friendly roles
    FRESHER_KEYWORDS: list = [
        "fresher", "freshers", "0 experience", "0-1 year", "0 to 1 year",
        "no experience", "entry level", "entry-level", "trainee",
    ]


class SchedulerConfig:
    """APScheduler job intervals."""
    NAUKRI_INTERVAL_HOURS: int = int(_get_env("SCHEDULER_NAUKRI_INTERVAL_HOURS", 4))
    FOUNDIT_INTERVAL_HOURS: int = int(
        _get_env("SCHEDULER_FOUNDIT_INTERVAL_HOURS", 6)
    )
    TIMESJOBS_INTERVAL_HOURS: int = int(
        _get_env("SCHEDULER_TIMESJOBS_INTERVAL_HOURS", 6)
    )

    TELEGRAM_POST_INTERVAL_MINUTES: int = int(
        _get_env("SCHEDULER_TELEGRAM_POST_INTERVAL_MINUTES", 15)
    )
    DAILY_DIGEST_HOUR: int = int(_get_env("SCHEDULER_DAILY_DIGEST_HOUR", 9))
    DAILY_DIGEST_MINUTE: int = int(_get_env("SCHEDULER_DAILY_DIGEST_MINUTE", 0))
    CLEANUP_DAYS: int = int(_get_env("SCHEDULER_CLEANUP_DAYS", 60))


class DeduplicationConfig:
    """Deduplication settings."""
    SIMILARITY_THRESHOLD: int = int(_get_env("DEDUP_SIMILARITY_THRESHOLD", 85))


class Config:
    """
    Single entry point for all configuration.

    Usage:
        from config import Config
        db_url = Config.database.URL
        token  = Config.telegram.BOT_TOKEN
    """
    database = DatabaseConfig()
    telegram = TelegramConfig()
    flask = FlaskConfig()
    logging = LoggingConfig()
    scraper = ScraperConfig()
    scheduler = SchedulerConfig()
    dedup = DeduplicationConfig()

    BASE_DIR: Path = BASE_DIR
    LOGS_DIR: Path = BASE_DIR / "logs"

    @classmethod
    def is_production(cls) -> bool:
        return cls.flask.ENV == "production"

    @classmethod
    def validate(cls) -> None:
        """Validate critical config at startup."""
        errors = []
        if not cls.database.URL:
            errors.append("DATABASE_URL is required")
        if not cls.flask.SECRET_KEY or cls.flask.SECRET_KEY == "dev-secret-change-me-in-production":
            if cls.is_production():
                errors.append("SECRET_KEY must be set in production")
        if errors:
            raise EnvironmentError(
                "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
            )
