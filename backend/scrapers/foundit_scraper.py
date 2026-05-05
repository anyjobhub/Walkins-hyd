"""
scrapers/foundit_scraper.py — Foundit (Monster India) job scraper.

Strategy:
  1. Requests + Headers (User-Agent, Accept-Language, Referer)
  2. Playwright (Fallback if 403 or blocked)
"""

from __future__ import annotations

import logging
import re
import time
import random
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

DEFAULT_CITIES = ["Hyderabad", "Bangalore", "Chennai"]
BASE_URL = "https://www.foundit.in"

FOUNDIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
}

class FounditScraper(BaseScraper):
    """Scrapes walk-in jobs from Foundit.in."""

    def __init__(self):
        super().__init__(source_name="foundit")
        self.cleaner = DataCleaner()

    def scrape_jobs(self, location="Hyderabad", keywords="walk-in", max_pages=2) -> List[Dict[str, Any]]:
        all_jobs = []
        logger.info("[foundit] Scraping %s | pages=%d", location, max_pages)

        for page in range(1, max_pages + 1):
            params = {
                "query": keywords,
                "locations": location,
                "start": (page - 1) * 15
            }
            url = f"{BASE_URL}/srp/results?{urlencode(params)}"
            
            # 1. Try requests with robust headers
            html = None
            try:
                resp = self._get(url, headers=FOUNDIT_HEADERS)
                if resp and resp.status_code == 200:
                    html = resp.text
                    logger.info("[foundit] %s p%d | Requests success", location, page)
                elif resp and resp.status_code == 403:
                    logger.warning("[foundit] %s p%d | 403 Forbidden, triggering Playwright fallback", location, page)
            except Exception as e:
                logger.error("[foundit] Request error for %s: %s", url, e)
            
            # 2. Try Playwright fallback
            if not html or "No jobs found" in html:
                html = self._get_playwright(url, wait_selector=".srpResultCard")

            if not html:
                logger.error("[foundit] Both methods failed for %s", url)
                continue

            page_jobs = self._parse_html(html)
            if not page_jobs: break
            
            all_jobs.extend(page_jobs)
            logger.info("[foundit] %s p%d → %d jobs found", location, page, len(page_jobs))
            time.sleep(random.uniform(3, 6))

        return all_jobs

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".srpResultCard") or soup.select("[class*='job-card']")
        jobs = []
        for card in cards:
            parsed = self.parse_job_listing(card)
            if parsed: jobs.append(parsed)
        return jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        try:
            job = self._build_base_job()
            title_el = element.select_one(".jobTitle") or element.select_one("h3 a")
            if not title_el: return None
            job["title"] = title_el.get_text(strip=True)
            
            link_el = title_el if title_el.name == "a" else title_el.select_one("a")
            if link_el and link_el.get("href"):
                href = link_el.get("href")
                job["job_url"] = href if href.startswith("http") else urljoin(BASE_URL, href)
                job["job_url"] = job["job_url"].split("?")[0] # Clean URL

            comp_el = element.select_one(".companyName") or element.select_one(".company-name")
            job["company"] = comp_el.get_text(strip=True) if comp_el else "Unknown"

            loc_el = element.select_one(".location") or element.select_one(".loc")
            job["location"] = loc_el.get_text(strip=True) if loc_el else "India"

            desc_el = element.select_one(".jobDescription")
            snippet = desc_el.get_text(strip=True) if desc_el else ""
            job["job_description"] = snippet

            combined = f"{job['title']} {snippet}".lower()
            job["is_walkin"] = "walk-in" in combined or "walkin" in combined
            job["is_fresher_friendly"] = "fresher" in combined or "0-1" in combined

            return job
        except Exception: return None

    def scrape_all_cities(self, cities=None) -> List[Dict[str, Any]]:
        cities = cities or DEFAULT_CITIES
        all_jobs = []
        seen = set()
        for city in cities:
            city_jobs = self.scrape_jobs(location=city)
            for j in city_jobs:
                if j["job_url"] not in seen:
                    seen.add(j["job_url"])
                    all_jobs.append(j)
        
        logger.info("[foundit] Total unique relevant jobs: %d", len(all_jobs))
        return all_jobs
