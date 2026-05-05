"""
scrapers/naukri_scraper.py — Naukri.com walk-in job scraper.

Strategy:
  1. Playwright (Primary) — Headless browser to handle dynamic JS content.
  2. Selenium (Fallback) — Headless Chrome if Playwright fails.
  3. City-based loops for Hyderabad, Bangalore, Chennai.
"""

from __future__ import annotations

import logging
import re
import time
import random
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_CITIES: List[str] = ["hyderabad", "bangalore", "chennai"]
NAUKRI_BASE = "https://www.naukri.com"

RELEVANCE_KEYWORDS: List[str] = [
    "walk-in", "walkin", "walk in", "direct interview", "spot interview",
    "open interview", "open house",
    "fresher", "freshers", "0 experience", "0-1 year", "entry level",
    "trainee", "graduate",
    "bpo", "voice", "customer support", "customer care", "call center",
    "non-it", "non it", "it support", "helpdesk", "data entry",
    "back office", "operations",
]


class NaukriScraper(BaseScraper):
    """Scrapes walk-in jobs from Naukri.com using browser automation."""

    BASE_URL = NAUKRI_BASE

    def __init__(self):
        super().__init__(source_name="naukri")
        self.cleaner = DataCleaner()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────
    def scrape_jobs(
        self,
        location: str = "hyderabad",
        keywords: str = "walk-in",
        max_pages: int = 2,
    ) -> List[Dict[str, Any]]:
        """Scrape walk-in jobs for a single city using Playwright -> Selenium."""
        all_jobs: List[Dict] = []
        city_slug = location.lower().replace(" ", "-")
        logger.info("Naukri | city=%s pages=%d", location, max_pages)

        for page in range(1, max_pages + 1):
            url = self._build_search_url(city_slug, page)
            html = None

            # 1. Try Playwright
            try:
                html = self._get_playwright(url, wait_selector="article.jobTuple")
                if html:
                    logger.info("Naukri | city=%s p%d | Playwright SUCCESS", location, page)
            except Exception as exc:
                logger.warning("Naukri | Playwright failed: %s", exc)

            # 2. Fallback to Selenium
            if not html:
                try:
                    html = self._get_selenium(url, wait_selector="article.jobTuple")
                    if html:
                        logger.info("Naukri | city=%s p%d | Selenium FALLBACK SUCCESS", location, page)
                except Exception as exc:
                    logger.error("Naukri | Selenium fallback failed: %s", exc)

            if not html:
                logger.error("Naukri | Both Playwright and Selenium failed for %s", url)
                continue

            # Parse results
            page_jobs = self._parse_html(html)
            if not page_jobs:
                logger.warning("Naukri | No job cards found on page %d", page)
                break

            all_jobs.extend(page_jobs)
            logger.info("Naukri | city=%s p%d → %d jobs", location, page, len(page_jobs))

            if page < max_pages:
                time.sleep(random.uniform(2, 5))

        return all_jobs

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        """Parse the full page HTML into job dicts."""
        soup = BeautifulSoup(html, "lxml")
        job_cards = (
            soup.select("article.jobTuple") or
            soup.select(".srp-jobtuple-wrapper") or
            soup.select("[class*='jobTuple']")
        )

        jobs = []
        for card in job_cards:
            parsed = self.parse_job_listing(card)
            if parsed and parsed.get("title"):
                jobs.append(parsed)
        return jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        """Parse a single BeautifulSoup job card."""
        try:
            job = self._build_base_job()

            title_el = (
                element.select_one("a.title") or
                element.select_one(".jobTitle a") or
                element.select_one("a[class*='title']")
            )
            if not title_el: return None
            job["title"] = title_el.get_text(strip=True)

            href = title_el.get("href", "")
            if href:
                job["job_url"] = href if href.startswith("http") else urljoin(NAUKRI_BASE, href)
                job["source_id"] = re.sub(r"[?#].*", "", href).strip("/").split("/")[-1]

            comp_el = element.select_one("a.comp-name") or element.select_one(".companyInfo a")
            job["company"] = comp_el.get_text(strip=True) if comp_el else "Unknown"

            loc_el = element.select_one("li.location") or element.select_one(".locWdth")
            if loc_el: job["location"] = loc_el.get_text(strip=True)

            exp_el = element.select_one("li.experience") or element.select_one(".expwdth")
            if exp_el:
                job["experience"] = exp_el.get_text(strip=True)
                job.update(self.cleaner.normalize_experience(job["experience"]))

            sal_el = element.select_one("li.salary") or element.select_one(".sal")
            if sal_el:
                job["salary"] = sal_el.get_text(strip=True)
                job.update(self.cleaner.normalize_salary(job["salary"]))

            desc_el = element.select_one(".job-description") or element.select_one(".cust-job-description")
            snippet = desc_el.get_text(strip=True) if desc_el else ""
            job["job_description"] = snippet

            # Walk-in / Fresher detection
            combined = f"{job['title']} {snippet} {job.get('location', '')}"
            job["is_walkin"] = self._detect_walkin(combined)
            job["is_fresher_friendly"] = self._detect_fresher(combined)

            if snippet:
                job.update(self.extract_walkin_details(snippet))

            return job
        except Exception:
            return None

    def scrape_all_cities(self, cities=None, max_pages=2) -> List[Dict[str, Any]]:
        """Multi-city loop for Hyderabad, Bangalore, Chennai."""
        cities = cities or DEFAULT_CITIES
        all_jobs = []
        seen_urls = set()

        for city in cities:
            logger.info("━━━ Naukri city=%s ━━━", city)
            city_jobs = self.scrape_jobs(location=city, max_pages=max_pages)
            for j in city_jobs:
                if j["job_url"] not in seen_urls:
                    seen_urls.add(j["job_url"])
                    if self.is_relevant(j):
                        all_jobs.append(j)

        logger.info("Naukri total unique jobs: %d", len(all_jobs))
        return all_jobs

    def _build_search_url(self, city: str, page: int) -> str:
        if page <= 1:
            return f"{NAUKRI_BASE}/walk-in-interview-jobs-in-{city}"
        return f"{NAUKRI_BASE}/walk-in-interview-jobs-in-{city}-{page}"

    def is_relevant(self, job: Dict[str, Any]) -> bool:
        haystack = f"{job.get('title')} {job.get('job_description')} {job.get('experience')}".lower()
        return any(kw in haystack for kw in RELEVANCE_KEYWORDS)

    def extract_walkin_details(self, text: str) -> Dict[str, Any]:
        """Extract date, time, venue, contact info."""
        res = {"walkin_dates":None, "walkin_time":None, "address":None, "contact_person":None, "contact_phone":None}
        if not text: return res
        
        # Simple patterns as requested
        date_m = re.search(r"(\d{1,2}(?:st|nd|rd|th)?\s*[A-Za-z]{3,}\s*(?:-\s*\d{1,2}(?:st|nd|rd|th)?\s*[A-Za-z]{3,})?)", text)
        if date_m: res["walkin_dates"] = date_m.group(1)

        time_m = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*(?:-\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))?)", text, re.I)
        if time_m: res["walkin_time"] = time_m.group(1)

        venue_m = re.search(r"(?:Venue|Address|Location)[:\s]+([^\n.]+)", text, re.I)
        if venue_m: res["address"] = venue_m.group(1).strip()

        contact_m = re.search(r"(?:Contact|Person|HR)[:\s]+([A-Za-z\s]{3,20})", text, re.I)
        if contact_m: res["contact_person"] = contact_m.group(1).strip()

        phone_m = re.search(r"(\d{10})", text)
        if phone_m: res["contact_phone"] = phone_m.group(1)

        return res
