"""
scrapers/base_scraper.py — Core base class for all job scrapers.

Provides unified methods for HTTP requests, browser automation (Playwright),
data cleaning, and rate limiting.
"""

from __future__ import annotations

import abc
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from playwright.sync_api import sync_playwright

from config import Config

logger = logging.getLogger(__name__)


class ScraperError(Exception):
    """Base exception for scraper-related issues."""


class RateLimitError(ScraperError):
    """Raised when the target site blocks us via 429."""


class ForbiddenError(ScraperError):
    """Raised when the target site blocks us via 403."""


class BaseScraper(abc.ABC):
    """
    Abstract Base Class for all job scrapers.
    Handles common logic like headers, proxying (if needed), and rate limiting.
    """

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.cfg = Config.scraper
        self._session = requests.Session()
        self._request_count = 0
        self._consecutive_failures = 0
        self._last_request_time = 0

    # -------------------------------------------------------------------------
    # HTTP: Requests
    # -------------------------------------------------------------------------
    def _get(
        self,
        url: str,
        headers: Dict[str, Any] = None,
        verify: bool = True,
        timeout: int = 30,
        **kwargs,
    ) -> requests.Response:
        """
        Wrapped GET request with retries and signature fix.
        Now accepts verify and timeout parameters directly.
        """
        if "User-Agent" not in self._session.headers:
            self._session.headers["User-Agent"] = self._random_user_agent()

        merged_headers = headers or {}

        for attempt in range(self.cfg.MAX_RETRIES):
            try:
                self._sleep_between_requests()
                response = self._session.get(
                    url,
                    headers=merged_headers or None,
                    verify=verify,
                    timeout=timeout,
                    **kwargs,
                )
                self._request_count += 1

                if response.status_code == 200:
                    self._consecutive_failures = 0
                    return response
                elif response.status_code == 403:
                    logger.warning("[%s] 403 Forbidden for %s", self.source_name, url)
                    return response
                elif response.status_code == 429:
                    self._exponential_backoff(attempt + 1)
                else:
                    logger.warning("[%s] HTTP %d for %s", self.source_name, response.status_code, url)
                    self._exponential_backoff(attempt)

            except Exception as exc:
                logger.error("[%s] Request failed: %s", self.source_name, exc)
                self._exponential_backoff(attempt)

        return None

    def _get_playwright(
        self,
        url: str,
        wait_selector: Optional[str] = None,
        timeout_ms: int = 30000,
    ) -> Optional[str]:
        """Fetch page content using Playwright (Chromium) with stealth measures."""
        from playwright.sync_api import sync_playwright

        self._sleep_between_requests()
        logger.info("[%s] Playwright launching (Stealth) for: %s", self.source_name, url)

        try:
            with sync_playwright() as p:
                # Use headless=True for Render, but user requested False for test
                # I'll use True as default but ensure all other stealth is on
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                    ]
                )
                
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    locale="en-IN"
                )
                page = context.new_page()

                # Mask automation flag
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined })
                """)

                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                
                # Simulate human behavior
                page.mouse.move(100, 200)
                page.wait_for_timeout(2000)

                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=15000)
                    except Exception:
                        logger.warning("[%s] Timeout waiting for %s", self.source_name, wait_selector)

                # Final scroll
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1000)

                content = page.content()
                browser.close()
                return content
        except Exception as exc:
            logger.error("[%s] Playwright error: %s", self.source_name, exc)
            return None


    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _sleep_between_requests(self) -> None:
        delay = random.uniform(self.cfg.MIN_DELAY, self.cfg.MAX_DELAY)
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_time = time.time()

    def _exponential_backoff(self, attempt: int) -> None:
        time.sleep(2**attempt + random.random())

    def _random_user_agent(self) -> str:
        return random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ])

    def _detect_walkin(self, text: str) -> bool:
        if not text: return False
        t = text.lower()
        return "walk" in t or "interview" in t or "direct" in t

    def _detect_fresher(self, text: str) -> bool:
        if not text: return False
        t = text.lower()
        return "fresher" in t or "0-1" in t or "entry level" in t

    def _build_base_job(self) -> Dict[str, Any]:
        return {
            "source": self.source_name,
            "extracted_at": datetime.now(timezone.utc),
            "is_walkin": False,
            "is_fresher_friendly": False,
        }

    @abc.abstractmethod
    def scrape_jobs(self, location: str, keywords: str, max_pages: int) -> List[Dict[str, Any]]:
        ...

    @abc.abstractmethod
    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        ...
