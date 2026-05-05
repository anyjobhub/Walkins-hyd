"""
scrapers/base_scraper.py — Abstract base class for all job scrapers.

Provides:
  - Rate limiting with configurable delay range
  - Exponential backoff retry logic
  - User-Agent rotation
  - robots.txt compliance check
  - Structured logging
  - Abstract interface all scrapers must implement
"""

from __future__ import annotations

import abc
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config

logger = logging.getLogger(__name__)


class ScraperError(Exception):
    """Base exception for all scraper errors."""
    pass


class RateLimitError(ScraperError):
    """Raised when the target server returns 429 Too Many Requests."""
    pass


class ForbiddenError(ScraperError):
    """Raised when the target server returns 403 Forbidden."""
    pass


class BaseScraper(abc.ABC):
    """
    Abstract base class for all job scrapers.

    Subclasses must implement:
      - scrape_jobs(location, keywords) -> List[Dict]
      - parse_job_listing(element) -> Dict

    Usage:
        class NaukriScraper(BaseScraper):
            def scrape_jobs(self, ...):
                ...
    """

    # Maximum number of consecutive failures before giving up
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.cfg = Config.scraper
        self._request_count = 0
        self._consecutive_failures = 0
        self._session = self._build_session()
        logger.info("Initialised %s scraper", source_name)

    # -------------------------------------------------------------------------
    # Session setup
    # -------------------------------------------------------------------------
    def _build_session(self) -> requests.Session:
        """
        Build a requests.Session with a retry adapter and default headers.

        The adapter retries on 500/502/503/504 (server errors) but NOT on
        429 or 403 — those are handled by our own logic.
        """
        session = requests.Session()

        retry_strategy = Retry(
            total=self.cfg.MAX_RETRIES,
            backoff_factor=2,                  # 2s, 4s, 8s …
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Set a default user agent (rotated per-request below)
        session.headers.update(self.cfg.DEFAULT_HEADERS)
        session.headers["User-Agent"] = self._random_user_agent()

        return session

    def _random_user_agent(self) -> str:
        """Return a random user-agent string from the configured list."""
        return random.choice(self.cfg.USER_AGENTS)

    # -------------------------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------------------------
    def _sleep_between_requests(self) -> None:
        """Sleep for a random duration within the configured delay range."""
        delay = random.uniform(self.cfg.DELAY_MIN, self.cfg.DELAY_MAX)
        logger.debug("Rate limiting: sleeping %.2fs before next request", delay)
        time.sleep(delay)

    def _exponential_backoff(self, attempt: int) -> None:
        """
        Sleep with exponential backoff: 2^attempt seconds (capped at 60s).

        Used after errors to avoid hammering the server.
        """
        wait = min(2 ** attempt, 60)
        logger.warning(
            "Backoff attempt %d: sleeping %ds before retry", attempt, wait
        )
        time.sleep(wait)

    # -------------------------------------------------------------------------
    # robots.txt compliance
    # -------------------------------------------------------------------------
    def _is_allowed_by_robots(self, url: str) -> bool:
        """
        Check if our user-agent is allowed to fetch the given URL
        according to the site's robots.txt.

        Returns True if allowed (or if robots.txt can't be fetched).
        """
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            allowed = rp.can_fetch("*", url)
            if not allowed:
                logger.warning(
                    "robots.txt disallows fetching %s — skipping", url
                )
            return allowed
        except Exception as exc:
            logger.debug("Could not check robots.txt for %s: %s", url, exc)
            return True   # Fail open — let subclass decide

    # -------------------------------------------------------------------------
    # Safe HTTP GET
    # -------------------------------------------------------------------------
    def _get(
        self,
        url: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        check_robots: bool = False,
    ) -> Optional[requests.Response]:
        """
        Perform a GET request with:
          - robots.txt check (optional)
          - Rate limiting sleep
          - User-Agent rotation
          - Error handling (403, 429, timeouts)

        Returns:
            requests.Response if successful, None on error.
        """
        if check_robots and not self._is_allowed_by_robots(url):
            return None

        self._sleep_between_requests()

        # Rotate user agent each request
        if self.cfg.ROTATE_USER_AGENTS:
            self._session.headers["User-Agent"] = self._random_user_agent()

        merged_headers = {}
        if headers:
            merged_headers.update(headers)

        for attempt in range(self.cfg.MAX_RETRIES):
            try:
                logger.debug("GET %s (attempt %d)", url, attempt + 1)
                response = self._session.get(
                    url,
                    params=params,
                    headers=merged_headers or None,
                    timeout=self.cfg.REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
                self._request_count += 1

                if response.status_code == 200:
                    self._consecutive_failures = 0
                    return response

                elif response.status_code == 429:
                    logger.error(
                        "429 Too Many Requests from %s — backing off", url
                    )
                    self._exponential_backoff(attempt + 1)
                    if attempt == self.cfg.MAX_RETRIES - 1:
                        raise RateLimitError(f"Rate limited by {url}")

                elif response.status_code == 403:
                    logger.error("403 Forbidden for %s — aborting", url)
                    raise ForbiddenError(f"Access forbidden: {url}")

                else:
                    logger.warning(
                        "Unexpected status %d for %s", response.status_code, url
                    )
                    self._exponential_backoff(attempt)

            except (RateLimitError, ForbiddenError):
                raise
            except requests.exceptions.Timeout:
                logger.warning("Timeout fetching %s (attempt %d)", url, attempt + 1)
                self._exponential_backoff(attempt)
            except requests.exceptions.ConnectionError as exc:
                logger.warning("Connection error for %s: %s", url, exc)
                self._exponential_backoff(attempt)
            except Exception as exc:
                logger.error("Unexpected error fetching %s: %s", url, exc, exc_info=True)
                self._exponential_backoff(attempt)

        self._consecutive_failures += 1
        logger.error("All %d attempts failed for %s", self.cfg.MAX_RETRIES, url)
        return None

    # -------------------------------------------------------------------------
    # Shared helpers
    # -------------------------------------------------------------------------
    def _detect_walkin(self, text: str) -> bool:
        """Return True if any walk-in keyword appears in text."""
        if not text:
            return False
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.cfg.WALKIN_KEYWORDS)

    def _detect_fresher(self, text: str) -> bool:
        """Return True if any fresher keyword appears in text."""
        if not text:
            return False
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.cfg.FRESHER_KEYWORDS)

    def _build_base_job(self) -> Dict[str, Any]:
        """Return a job dict pre-populated with source name and timestamp."""
        return {
            "source": self.source_name,
            "extracted_at": datetime.now(timezone.utc),
            "is_walkin": False,
            "is_fresher_friendly": False,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return scraper statistics for monitoring."""
        return {
            "source": self.source_name,
            "request_count": self._request_count,
            "consecutive_failures": self._consecutive_failures,
        }

    # -------------------------------------------------------------------------
    # Abstract interface
    # -------------------------------------------------------------------------
    @abc.abstractmethod
    def scrape_jobs(
        self,
        location: str = "India",
        keywords: str = "walk-in",
        max_pages: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Scrape job listings from the source.

        Args:
            location: City or country to search in.
            keywords: Search terms.
            max_pages: Maximum number of result pages to scrape.

        Returns:
            List of job dictionaries, each matching the Job model fields.
        """
        ...

    @abc.abstractmethod
    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        """
        Parse a single job listing element into a job dictionary.

        Args:
            element: HTML element or dict representing a job listing.

        Returns:
            Job dict or None if parsing fails.
        """
        ...
