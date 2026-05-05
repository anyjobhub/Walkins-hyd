"""
scrapers/naukri_scraper.py — Naukri.com walk-in job scraper.

Strategy:
  1. Playwright (Primary) — Headless browser to handle dynamic JS content.
  2. Scrolling logic to trigger lazy loading of job cards.
  3. Robust selectors with fallbacks.
"""

from __future__ import annotations

import logging
import re
import time
import random
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

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
    """Scrapes walk-in jobs from Naukri.com using Playwright with advanced waiting/scrolling."""

    def __init__(self):
        super().__init__(source_name="naukri")
        self.cleaner = DataCleaner()

    def scrape_jobs(self, location: str = "hyderabad", keywords: str = "walk-in", max_pages: int = 2) -> List[Dict[str, Any]]:
        all_jobs: List[Dict] = []
        city_slug = location.lower().replace(" ", "-")
        logger.info("[naukri] Scraping %s | pages=%d", location, max_pages)

        for page in range(1, max_pages + 1):
            url = self._build_search_url(city_slug, page)
            
            # Explicitly using sync_playwright here to implement the specific wait/scroll logic
            html = self._fetch_dynamic_content(url)

            if not html:
                logger.error("[naukri] Failed to fetch content for %s", url)
                continue

            page_jobs = self._parse_html(html)
            if not page_jobs:
                logger.warning("[naukri] No job cards found on page %d for %s", page, location)
                # Print debug content as requested
                logger.debug("Page Content Preview: %s", html[:1000])
                break

            all_jobs.extend(page_jobs)
            logger.info("[naukri] %s p%d → %d jobs found", location, page, len(page_jobs))

            if page < max_pages:
                time.sleep(random.uniform(4, 8))

        return all_jobs

    def _fetch_dynamic_content(self, url: str) -> Optional[str]:
        """Custom fetch with scrolling and smart waits."""
        try:
            with sync_playwright() as p:
                # Launching with --no-sandbox as required for Render
                # Headless=True for production, can be toggled for local debug
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = context.new_page()
                
                logger.info("[naukri] Navigating to %s", url)
                # Use mobile version sometimes as suggested
                target_url = f"{url}?isMobile=true" if random.random() > 0.5 else url
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)

                # Smart Wait
                try:
                    page.wait_for_selector("div, article", timeout=15000)
                except Exception:
                    pass

                # VERY IMPORTANT: Scroll to trigger lazy loading
                logger.info("[naukri] Scrolling to trigger lazy load...")
                for _ in range(3):
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(2000)

                content = page.content()
                browser.close()
                return content
        except Exception as exc:
            logger.error("[naukri] Playwright error: %s", exc)
            return None

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        """Parse using robust selectors with fallbacks."""
        soup = BeautifulSoup(html, "lxml")
        
        # Multiple fallback selectors
        job_cards = (
            soup.select("article.jobTuple") or 
            soup.select(".srp-jobtuple-wrapper") or
            soup.select("div.jobTuple") or
            soup.select("div.cust-job-tuple") or
            soup.select("div.row1") or
            soup.select("[class*='jobTuple']")
        )

        jobs = []
        for card in job_cards:
            parsed = self.parse_job_listing(card)
            if parsed and parsed.get("title"):
                jobs.append(parsed)
        return jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        try:
            job = self._build_base_job()

            title_el = (
                element.select_one("a.title") or
                element.select_one(".jobTitle a") or
                element.select_one("a[class*='title']") or
                element.select_one("h2") or
                element.select_one("h3")
            )
            if not title_el: return None
            job["title"] = title_el.get_text(strip=True)

            href = title_el.get("href", "") if title_el.name == "a" else (title_el.select_one("a").get("href", "") if title_el.select_one("a") else "")
            if href:
                job["job_url"] = href if href.startswith("http") else urljoin(NAUKRI_BASE, href)
                job["source_id"] = re.sub(r"[?#].*", "", href).strip("/").split("/")[-1]

            comp_el = element.select_one("a.comp-name") or element.select_one(".companyInfo a") or element.select_one(".comp-name-short")
            job["company"] = comp_el.get_text(strip=True) if comp_el else "Unknown"

            loc_el = element.select_one("li.location") or element.select_one(".locWdth") or element.select_one(".loc")
            if loc_el: job["location"] = loc_el.get_text(strip=True)

            exp_el = element.select_one("li.experience") or element.select_one(".expwdth")
            if exp_el:
                job["experience"] = exp_el.get_text(strip=True)
                job.update(self.cleaner.normalize_experience(job["experience"]))

            desc_el = element.select_one(".job-description") or element.select_one(".cust-job-description")
            snippet = desc_el.get_text(strip=True) if desc_el else ""
            job["job_description"] = snippet

            # Walk-in / Fresher detection
            combined = f"{job['title']} {snippet} {job.get('location', '')}".lower()
            job["is_walkin"] = self._detect_walkin(combined)
            job["is_fresher_friendly"] = self._detect_fresher(combined)

            if snippet:
                job.update(self.extract_walkin_details(snippet))

            return job
        except Exception:
            return None

    def scrape_all_cities(self, cities=None) -> List[Dict[str, Any]]:
        cities = cities or DEFAULT_CITIES
        all_jobs = []
        seen_urls = set()

        for city in cities:
            logger.info("━━━ Naukri city=%s ━━━", city)
            city_jobs = self.scrape_jobs(location=city, max_pages=2)
            for j in city_jobs:
                if j["job_url"] not in seen_urls:
                    seen_urls.add(j["job_url"])
                    if self.is_relevant(j):
                        all_jobs.append(j)

        logger.info("[naukri] Total unique relevant jobs: %d", len(all_jobs))
        return all_jobs

    def _build_search_url(self, city: str, page: int) -> str:
        if page <= 1:
            return f"{NAUKRI_BASE}/walk-in-interview-jobs-in-{city}"
        return f"{NAUKRI_BASE}/walk-in-interview-jobs-in-{city}-{page}"

    def is_relevant(self, job: Dict[str, Any]) -> bool:
        haystack = f"{job.get('title')} {job.get('job_description')} {job.get('experience')}".lower()
        return any(kw in haystack for kw in RELEVANCE_KEYWORDS)

    def extract_walkin_details(self, text: str) -> Dict[str, Any]:
        res = {"walkin_dates":None, "walkin_time":None, "address":None, "contact_person":None, "contact_phone":None}
        if not text: return res
        date_m = re.search(r"(\d{1,2}(?:st|nd|rd|th)?\s*[A-Za-z]{3,}\s*(?:-\s*\d{1,2}(?:st|nd|rd|th)?\s*[A-Za-z]{3,})?)", text)
        if date_m: res["walkin_dates"] = date_m.group(1)
        phone_m = re.search(r"(\d{10})", text)
        if phone_m: res["contact_phone"] = phone_m.group(1)
        return res
