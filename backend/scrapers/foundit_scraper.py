"""
scrapers/foundit_scraper.py — Foundit (Monster India) job scraper.

Strategy:
  1. Requests + BeautifulSoup (Step 1)
  2. Playwright (Fallback)
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

class FounditScraper(BaseScraper):
    """Scrapes walk-in jobs from Foundit.in."""

    def __init__(self):
        super().__init__(source_name="foundit")
        self.cleaner = DataCleaner()

    def scrape_jobs(self, location="Hyderabad", keywords="walk-in", max_pages=2) -> List[Dict[str, Any]]:
        all_jobs = []
        logger.info("Foundit | city=%s", location)

        for page in range(1, max_pages + 1):
            params = {
                "query": keywords,
                "locations": location,
                "start": (page - 1) * 15
            }
            url = f"{BASE_URL}/srp/results?{urlencode(params)}"
            
            # 1. Try requests
            html = None
            resp = self._get(url)
            if resp and resp.status_code == 200:
                html = resp.text
                logger.info("Foundit | city=%s p%d | requests SUCCESS", location, page)
            
            # 2. Try Playwright fallback
            if not html or "No jobs found" in html or len(html) < 5000:
                logger.info("Foundit | requests failed or empty, trying Playwright...")
                html = self._get_playwright(url, wait_selector=".srpResultCard")

            if not html:
                logger.error("Foundit | Both methods failed for %s", url)
                continue

            page_jobs = self._parse_html(html)
            if not page_jobs: break
            
            all_jobs.extend(page_jobs)
            logger.info("Foundit | city=%s p%d → %d jobs", location, page, len(page_jobs))
            time.sleep(random.uniform(2, 5))

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
                job["source_id"] = job["job_url"].split("-")[-1].split("?")[0]

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

            if snippet:
                job.update(self._extract_details(snippet))

            return job
        except Exception: return None

    def _extract_details(self, text: str) -> Dict:
        res = {"walkin_dates":None, "walkin_time":None, "address":None, "contact_person":None, "contact_phone":None}
        # Reusing basic regex from Naukri
        date_m = re.search(r"(\d{1,2}(?:st|nd|rd|th)?\s*[A-Za-z]{3,}\s*(?:-\s*\d{1,2}(?:st|nd|rd|th)?\s*[A-Za-z]{3,})?)", text)
        if date_m: res["walkin_dates"] = date_m.group(1)
        phone_m = re.search(r"(\d{10})", text)
        if phone_m: res["contact_phone"] = phone_m.group(1)
        return res

    def scrape_all_cities(self, cities=None) -> List[Dict[str, Any]]:
        cities = cities or DEFAULT_CITIES
        all_jobs = []
        seen = set()
        for city in cities:
            logger.info("━━━ Foundit city=%s ━━━", city)
            city_jobs = self.scrape_jobs(location=city)
            for j in city_jobs:
                if j["job_url"] not in seen:
                    seen.add(j["job_url"])
                    all_jobs.append(j)
        return all_jobs
