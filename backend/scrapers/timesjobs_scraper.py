"""
scrapers/timesjobs_scraper.py — TimesJobs walk-in job scraper.

Strategy:
  1. Requests + SSL Verify=False (to handle certificate issues)
  2. Playwright (Fallback)
"""

from __future__ import annotations

import logging
import re
import time
import random
import urllib3
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from services.data_cleaner import DataCleaner

# Disable SSL warnings as requested
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

DEFAULT_CITIES = ["Hyderabad", "Bangalore", "Chennai"]
BASE_URL = "https://www.timesjobs.com"

class TimesJobsScraper(BaseScraper):
    """Scrapes walk-in jobs from TimesJobs.com."""

    def __init__(self):
        super().__init__(source_name="timesjobs")
        self.cleaner = DataCleaner()

    def scrape_jobs(self, location="Hyderabad", keywords="walk-in", max_pages=2) -> List[Dict[str, Any]]:
        all_jobs = []
        logger.info("[timesjobs] Scraping %s | pages=%d", location, max_pages)

        for page in range(1, max_pages + 1):
            params = {
                "from": "submit",
                "searchType": "personalizedSearch",
                "luceneResultSize": 25,
                "postWeek": 60,
                "txtKeywords": keywords,
                "txtLocation": location,
                "sequence": page,
                "startPage": 1
            }
            url = f"{BASE_URL}/candidate/job-search.html?{urlencode(params)}"
            
            html = None
            try:
                # verify=False is now supported via **kwargs in BaseScraper._get()
                resp = self._get(url, verify=False)
                if resp and resp.status_code == 200:
                    html = resp.text
                    logger.info("[timesjobs] %s p%d | Requests success", location, page)
            except Exception as e:
                logger.error("[timesjobs] SSL/Request error for %s: %s", url, e)
            
            if not html or "No Jobs found" in html:
                logger.info("[timesjobs] Requests failed or SSL issue, trying Playwright...")
                html = self._get_playwright(url, wait_selector=".job-bx")

            if not html: continue

            page_jobs = self._parse_html(html)
            if not page_jobs: break
            
            all_jobs.extend(page_jobs)
            logger.info("[timesjobs] %s p%d → %d jobs found", location, page, len(page_jobs))
            time.sleep(random.uniform(4, 8))

        return all_jobs

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".job-bx") or soup.select(".clearfix.job-bx")
        jobs = []
        for card in cards:
            parsed = self.parse_job_listing(card)
            if parsed: jobs.append(parsed)
        return jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        try:
            job = self._build_base_job()
            title_el = element.select_one("h2 a")
            if not title_el: return None
            job["title"] = title_el.get_text(strip=True)
            job["job_url"] = title_el.get("href")
            
            if job["job_url"]:
                job["job_url"] = job["job_url"].split("?")[0]

            comp_el = element.select_one("h3.joblist-comp-name")
            job["company"] = comp_el.get_text(strip=True).split("(")[0].strip() if comp_el else "Unknown"

            loc_el = element.select_one("span[title]")
            job["location"] = loc_el.get_text(strip=True) if loc_el else "India"

            desc_el = element.select_one(".job-description") or element.select_one("ul.list-job-dtl")
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
            logger.info("━━━ TimesJobs city=%s ━━━", city)
            city_jobs = self.scrape_jobs(location=city)
            for j in city_jobs:
                if j["job_url"] not in seen:
                    seen.add(j["job_url"])
                    all_jobs.append(j)
        return all_jobs
