"""
scrapers/foundit_scraper.py — Foundit (Monster India) job scraper.

Updated with verified selectors (May 2026):
- Card: .srpCardContainer
- Title: .jobTitle
- Company: .companyName
"""

from __future__ import annotations

import logging
import re
import time
import random
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from scrapers.base_scraper import BaseScraper
from services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

DEFAULT_CITIES = ["Hyderabad", "Bangalore", "Chennai"]
BASE_URL = "https://www.foundit.in"

class FounditScraper(BaseScraper):
    """Scrapes walk-in jobs from Foundit.in using updated selectors."""

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
            
            html = self._fetch_foundit_content(url)
            if not html: continue

            page_jobs = self._parse_html(html)
            if not page_jobs: break
            
            all_jobs.extend(page_jobs)
            logger.info("[foundit] %s p%d → %d jobs", location, page, len(page_jobs))
            time.sleep(random.uniform(5, 8))

        return all_jobs

    def _fetch_foundit_content(self, url: str) -> Optional[str]:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = context.new_page()
                
                # Increased timeout as requested
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000) # Anti-bot delay
                
                # Wait for results
                try:
                    page.wait_for_selector(".srpCardContainer, .srpResultCard", timeout=10000)
                except:
                    pass

                content = page.content()
                browser.close()
                return content
        except Exception as e:
            logger.error("[foundit] Playwright error: %s", e)
            return None

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        # Updated selector: .srpCardContainer
        cards = soup.select(".srpCardContainer") or soup.select(".srpResultCard") or soup.select("[class*='job-card']")
        
        jobs = []
        for card in cards:
            parsed = self.parse_job_listing(card)
            if parsed: jobs.append(parsed)
        return jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        try:
            job = self._build_base_job()
            
            # Updated selectors
            title_el = element.select_one(".jobTitle") or element.select_one("h3 a")
            if not title_el: return None
            job["title"] = title_el.get_text(strip=True)
            
            link_el = title_el if title_el.name == "a" else title_el.select_one("a")
            if link_el and link_el.get("href"):
                href = link_el.get("href")
                job["job_url"] = href if href.startswith("http") else urljoin(BASE_URL, href)
                job["job_url"] = job["job_url"].split("?")[0]

            comp_el = element.select_one(".companyName") or element.select_one(".company-name")
            job["company"] = comp_el.get_text(strip=True) if comp_el else "Unknown"

            loc_el = element.select_one(".location") or element.select_one(".loc")
            job["location"] = loc_el.get_text(strip=True) if loc_el else "India"

            # Foundit details (Experience/Salary)
            details = element.select(".experienceSalary .details")
            if details:
                job["experience"] = details[0].get_text(strip=True)
                if len(details) > 1:
                    job["salary"] = details[1].get_text(strip=True)

            snippet_el = element.select_one(".jobDescription") or element.select_one(".description")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            job["job_description"] = snippet

            combined = f"{job['title']} {snippet}".lower()
            job["is_walkin"] = "walk" in combined or "interview" in combined
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
        return all_jobs
