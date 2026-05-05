"""
scrapers/naukri_scraper.py — Naukri.com walk-in job scraper.

Updated with verified selectors (May 2026):
- Card: div.srp-jobtuple-wrapper
- Title: a.title
- Company: a.comp-name
- Location: .locWdth2
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

DEFAULT_CITIES = ["hyderabad", "bangalore", "chennai"]
NAUKRI_BASE = "https://www.naukri.com"

class NaukriScraper(BaseScraper):
    """Scrapes walk-in jobs from Naukri.com using updated selectors."""

    def __init__(self):
        super().__init__(source_name="naukri")
        self.cleaner = DataCleaner()

    def scrape_jobs(self, location="hyderabad", keywords="walk-in", max_pages=2) -> List[Dict[str, Any]]:
        all_jobs = []
        city_slug = location.lower().replace(" ", "-")
        logger.info("[naukri] Scraping %s | pages=%d", location, max_pages)

        for page in range(1, max_pages + 1):
            url = f"{NAUKRI_BASE}/walk-in-interview-jobs-in-{city_slug}"
            if page > 1: url += f"-{page}"
            
            html = self._fetch_naukri_content(url)
            if not html: continue

            page_jobs = self._parse_html(html)
            if not page_jobs:
                logger.warning("[naukri] No job cards found for %s p%d", location, page)
                break

            all_jobs.extend(page_jobs)
            logger.info("[naukri] %s p%d → %d jobs", location, page, len(page_jobs))
            time.sleep(random.uniform(3, 6))

        return all_jobs

    def _fetch_naukri_content(self, url: str) -> Optional[str]:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = context.new_page()
                
                # Navigate and wait for content
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Scroll to trigger lazy loading (VERY IMPORTANT)
                for _ in range(3):
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(1500)
                
                # Wait for any job card to appear
                try:
                    page.wait_for_selector(".srp-jobtuple-wrapper, article", timeout=10000)
                except:
                    pass

                content = page.content()
                browser.close()
                return content
        except Exception as e:
            logger.error("[naukri] Playwright error: %s", e)
            return None

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        # Updated selector: .srp-jobtuple-wrapper
        job_cards = soup.select(".srp-jobtuple-wrapper") or soup.select("article.jobTuple") or soup.select("div.jobTuple")
        
        jobs = []
        for card in job_cards:
            parsed = self.parse_job_listing(card)
            if parsed: jobs.append(parsed)
        return jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        try:
            job = self._build_base_job()
            
            # Updated selectors
            title_el = element.select_one("a.title") or element.select_one(".jobTitle a")
            if not title_el: return None
            job["title"] = title_el.get_text(strip=True)
            
            href = title_el.get("href", "")
            job["job_url"] = href if href.startswith("http") else urljoin(NAUKRI_BASE, href)
            job["source_id"] = job["job_url"].split("-")[-1].split("?")[0]

            comp_el = element.select_one("a.comp-name") or element.select_one(".companyInfo a")
            job["company"] = comp_el.get_text(strip=True) if comp_el else "Unknown"

            loc_el = element.select_one(".locWdth2") or element.select_one("li.location")
            job["location"] = loc_el.get_text(strip=True) if loc_el else "India"

            exp_el = element.select_one(".exp-wrap") or element.select_one("li.experience")
            if exp_el:
                job["experience"] = exp_el.get_text(strip=True)
                job.update(self.cleaner.normalize_experience(job["experience"]))

            desc_el = element.select_one(".job-desc") or element.select_one(".job-description")
            snippet = desc_el.get_text(strip=True) if desc_el else ""
            job["job_description"] = snippet

            # Walk-in detection
            combined = f"{job['title']} {snippet}".lower()
            job["is_walkin"] = "walk" in combined or "interview" in combined or bool(element.select_one(".ttc__walk-in"))
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
