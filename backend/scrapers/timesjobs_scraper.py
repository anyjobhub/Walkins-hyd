"""
scrapers/timesjobs_scraper.py — TimesJobs walk-in job scraper.

Updated with verified selectors (May 2026):
- Card: .srp-card
- Title: h2
- Company: .text-gray-400 span:first-child
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
from playwright.sync_api import sync_playwright

from scrapers.base_scraper import BaseScraper
from services.data_cleaner import DataCleaner

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

DEFAULT_CITIES = ["Hyderabad", "Bangalore", "Chennai"]
BASE_URL = "https://www.timesjobs.com"

class TimesJobsScraper(BaseScraper):
    """Scrapes walk-in jobs from TimesJobs.com using updated selectors."""

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
            
            html = self._fetch_timesjobs_content(url)
            if not html: continue

            page_jobs = self._parse_html(html)
            if not page_jobs: break
            
            all_jobs.extend(page_jobs)
            logger.info("[timesjobs] %s p%d → %d jobs", location, page, len(page_jobs))
            time.sleep(random.uniform(4, 8))

        return all_jobs

    def _fetch_timesjobs_content(self, url: str) -> Optional[str]:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = context.new_page()
                
                # Increased timeout to 60s as requested
                logger.info("[timesjobs] Navigating with 60s timeout...")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2000)
                    content = page.content()
                    browser.close()
                    return content
                except Exception as e:
                    logger.warning("[timesjobs] Timeout for %s, skipping...", url)
                    browser.close()
                    return None
        except Exception as e:
            logger.error("[timesjobs] Playwright error: %s", e)
            return None

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        # Updated selector: .srp-card
        cards = soup.select(".srp-card") or soup.select(".job-bx") or soup.select(".clearfix.job-bx")
        
        jobs = []
        for card in cards:
            parsed = self.parse_job_listing(card)
            if parsed: jobs.append(parsed)
        return jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        try:
            job = self._build_base_job()
            
            # Updated selectors
            title_el = element.select_one("h2 a") or element.select_one("h2")
            if not title_el: return None
            job["title"] = title_el.get_text(strip=True)
            
            link_el = title_el if title_el.name == "a" else title_el.select_one("a")
            if link_el:
                job["job_url"] = link_el.get("href")
                if job["job_url"]: job["job_url"] = job["job_url"].split("?")[0]

            # Company: .text-gray-400 span:first-child
            comp_el = element.select_one(".text-gray-400 span") or element.select_one("h3.joblist-comp-name")
            job["company"] = comp_el.get_text(strip=True).split("(")[0].strip() if comp_el else "Unknown"

            loc_el = element.select_one("i.locations-icon")
            if loc_el:
                job["location"] = loc_el.parent.get_text(strip=True)
            else:
                loc_el = element.select_one("span[title]")
                job["location"] = loc_el.get_text(strip=True) if loc_el else "India"

            exp_el = element.select_one("i.years-icon")
            if exp_el:
                job["experience"] = exp_el.parent.get_text(strip=True)

            sal_el = element.select_one("i.salary-icon")
            if sal_el:
                job["salary"] = sal_el.parent.get_text(strip=True)

            desc_el = element.select_one(".job-description") or element.select_one("ul.list-job-dtl")
            snippet = desc_el.get_text(strip=True) if desc_el else ""
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
            logger.info("━━━ TimesJobs city=%s ━━━", city)
            city_jobs = self.scrape_jobs(location=city)
            for j in city_jobs:
                if j["job_url"] not in seen:
                    seen.add(j["job_url"])
                    all_jobs.append(j)
        return all_jobs
