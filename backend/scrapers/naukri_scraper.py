"""
scrapers/naukri_scraper.py — Naukri.com walk-in job scraper (HTML-based).

Strategy:
  - Scrapes Naukri search pages directly using requests + BeautifulSoup.
  - URL pattern: https://www.naukri.com/walk-in-interview-jobs-in-{city}-{page}
  - Multi-city: Hyderabad, Bangalore, Chennai.
  - Robust selectors for job cards: article.jobTuple, .srp-jobtuple-wrapper.
  - 2-5 second polite delay between requests.
"""

from __future__ import annotations

import logging
import re
import time
import random
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, ForbiddenError, RateLimitError
from services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_CITIES: List[str] = ["hyderabad", "bangalore", "chennai"]
NAUKRI_BASE = "https://www.naukri.com"

# Chrome-like headers as requested by user
NAUKRI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

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
    """Scrapes walk-in jobs from Naukri.com using HTML + BeautifulSoup."""

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
        """Scrape walk-in jobs for a single city."""
        all_jobs: List[Dict] = []
        city_slug = location.lower().replace(" ", "-")
        logger.info("Naukri | city=%s pages=%d", location, max_pages)

        for page in range(1, max_pages + 1):
            try:
                page_jobs = self._scrape_page(city_slug, page)
                if not page_jobs:
                    logger.warning("Naukri | city=%s page=%d → No jobs found, skipping city", location, page)
                    break
                all_jobs.extend(page_jobs)
                logger.info("Naukri | city=%s page=%d → %d jobs (total %d)",
                            location, page, len(page_jobs), len(all_jobs))
                # Polite delay between pages (2-5 sec as requested)
                time.sleep(random.uniform(2, 5))
            except (RateLimitError, ForbiddenError) as exc:
                logger.error("Naukri blocked for %s: %s", location, exc)
                break
            except Exception as exc:
                logger.error("Naukri page error city=%s page=%d: %s", location, page, exc)
                continue

        return all_jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        """Parse a single BeautifulSoup job card into a job dict."""
        try:
            job = self._build_base_job()

            # ── Title ─────────────────────────────────────────────────────
            # a.title as requested
            title_el = (
                element.select_one("a.title") or
                element.select_one(".jobTitle a") or
                element.select_one("a[class*='title']") or
                element.select_one("h2 a")
            )
            if not title_el:
                return None
            job["title"] = title_el.get_text(strip=True)
            if not job["title"]:
                return None

            # ── Job URL ───────────────────────────────────────────────────
            href = title_el.get("href", "")
            if href:
                job["job_url"] = href if href.startswith("http") else urljoin(NAUKRI_BASE, href)
                job["source_id"] = re.sub(r"[?#].*", "", href).strip("/").split("/")[-1]

            # ── Company ───────────────────────────────────────────────────
            company_el = (
                element.select_one("a.comp-name") or
                element.select_one(".companyInfo a") or
                element.select_one("[class*='company-name']")
            )
            job["company"] = company_el.get_text(strip=True) if company_el else "Unknown"

            # ── Location ──────────────────────────────────────────────────
            loc_el = (
                element.select_one("li.location") or
                element.select_one(".locWdth") or
                element.select_one("span[class*='location']")
            )
            if loc_el:
                job["location"] = loc_el.get_text(strip=True)

            # ── Experience ────────────────────────────────────────────────
            exp_el = (
                element.select_one("li.experience") or
                element.select_one(".expwdth")
            )
            if exp_el:
                job["experience"] = exp_el.get_text(strip=True)
                job.update(self.cleaner.normalize_experience(job["experience"]))

            # ── Salary ────────────────────────────────────────────────────
            sal_el = (
                element.select_one("li.salary") or
                element.select_one(".sal")
            )
            if sal_el:
                job["salary"] = sal_el.get_text(strip=True)
                job.update(self.cleaner.normalize_salary(job["salary"]))

            # ── Skills / Tags ─────────────────────────────────────────────
            skills_els = element.select("li.tag, .tags li, [class*='skill']")
            if skills_els:
                job["skills"] = self.cleaner.clean_skills_array(
                    ", ".join(el.get_text(strip=True) for el in skills_els)
                )

            # ── Description snippet ───────────────────────────────────────
            desc_el = element.select_one(".job-description, [class*='desc']")
            snippet = desc_el.get_text(strip=True) if desc_el else ""
            job["job_description"] = snippet

            # ── Walk-in / Fresher detection ───────────────────────────────
            combined = f"{job['title']} {snippet} {job.get('location', '')}"
            job["is_walkin"]           = self._detect_walkin(combined)
            job["is_fresher_friendly"] = self._detect_fresher(combined)

            # ── Walk-in detail extraction ─────────────────────────────────
            if snippet:
                walkin_info = self.extract_walkin_details(snippet)
                for key, val in walkin_info.items():
                    if val and not job.get(key):
                        job[key] = val

            return job

        except Exception as exc:
            logger.debug("Failed to parse Naukri job card: %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Multi-city orchestrator
    # ─────────────────────────────────────────────────────────────────────────
    def scrape_all_cities(
        self,
        cities: List[str] = None,
        keywords: str = "walk-in",
        max_pages: int = 2,
        filter_relevant: bool = True,
    ) -> List[Dict[str, Any]]:
        """Scrape Hyderabad, Bangalore, Chennai as requested."""
        cities = cities or DEFAULT_CITIES
        seen_urls: Set[str] = set()
        all_jobs: List[Dict[str, Any]] = []

        for city in cities:
            logger.info("━━━ Naukri | city=%-12s ━━━", city)
            try:
                city_jobs = self.scrape_jobs(location=city, keywords=keywords, max_pages=max_pages)
                if not city_jobs:
                    logger.warning("Naukri | No jobs found for city=%s, continuing to next city", city)
            except Exception as exc:
                logger.error("Naukri failed for city=%s: %s", city, exc)
                continue

            added = 0
            for job in city_jobs:
                url = job.get("job_url", "")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                if filter_relevant and not self.is_relevant(job):
                    continue
                all_jobs.append(job)
                added += 1

            logger.info("Naukri | city=%-12s scraped=%d  kept=%d", city, len(city_jobs), added)

        logger.info("Naukri scrape_all_cities done | total=%d", len(all_jobs))
        return all_jobs

    # ─────────────────────────────────────────────────────────────────────────
    # Internal: HTML page scraper
    # ─────────────────────────────────────────────────────────────────────────
    def _build_search_url(self, city_slug: str, page: int) -> str:
        """
        Build Naukri walk-in search URL as requested.
        Pattern: https://www.naukri.com/walk-in-interview-jobs-in-{city}-{page}
        """
        if page <= 1:
            return f"{NAUKRI_BASE}/walk-in-interview-jobs-in-{city_slug}"
        return f"{NAUKRI_BASE}/walk-in-interview-jobs-in-{city_slug}-{page}"

    def _scrape_page(self, city_slug: str, page: int) -> List[Dict[str, Any]]:
        """Fetch one Naukri search page and extract all job cards."""
        url = self._build_search_url(city_slug, page)
        logger.info("Naukri fetching: %s", url)

        response = self._get(url, headers=NAUKRI_HEADERS, check_robots=False)
        if not response:
            logger.warning("Naukri: no response for %s", url)
            return []

        if response.status_code != 200:
            logger.warning("Naukri: HTTP %d for %s", response.status_code, url)
            return []

        soup = BeautifulSoup(response.text, "lxml")

        # Required selectors as requested by user
        job_cards = (
            soup.select("article.jobTuple") or
            soup.select(".srp-jobtuple-wrapper") or
            soup.select("[class*='jobTuple']") or
            soup.select(".job-tuple")
        )

        logger.info("Naukri | url=%s → %d job cards found", url, len(job_cards))

        if not job_cards:
            return []

        jobs = []
        for card in job_cards:
            parsed = self.parse_job_listing(card)
            if parsed and parsed.get("title"):
                jobs.append(parsed)

        return jobs

    # ─────────────────────────────────────────────────────────────────────────
    # Walk-in detail extractor
    # ─────────────────────────────────────────────────────────────────────────
    def extract_walkin_details(self, text: str) -> Dict[str, Any]:
        """Extract walkin_dates, walkin_time, address, contact_person, contact_phone."""
        result: Dict[str, Any] = {
            "walkin_dates": None, "walkin_time": None,
            "address": None, "contact_person": None, "contact_phone": None,
        }
        if not text:
            return result

        MONTHS = (
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?"
            r"|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?"
            r"|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        )
        for pat in [
            rf"(\d{{1,2}}(?:st|nd|rd|th)?\s*(?:[&,/-]+\s*\d{{1,2}}(?:st|nd|rd|th)?\s*)?{MONTHS}(?:\s+\d{{4}})?)",
            rf"(?:walk[- ]?in\s+)?date[s]?[:\s]+([\w\s,&/-]{{5,40}})",
            rf"({MONTHS}\s+\d{{1,2}}(?:,\s*\d{{4}})?)",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result["walkin_dates"] = m.group(1).strip()
                break

        tm = re.search(
            r"(?:time|timing)[:\s]*(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*(?:[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))?)",
            text, re.IGNORECASE,
        ) or re.search(
            r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))",
            text, re.IGNORECASE,
        )
        if tm:
            result["walkin_time"] = tm.group(1).strip()

        vm = re.search(
            r"(?:venue|address|location|walk[- ]?in\s+at|office(?:\s+address)?)[:\s]+([^\n.]{10,200})",
            text, re.IGNORECASE,
        )
        if vm:
            result["address"] = vm.group(1).strip()

        cp = re.search(
            r"(?:contact(?:\s+person)?|hr\s+(?:name|contact)|reach\s+(?:out\s+to)?)[:\s]+"
            r"([A-Za-z][A-Za-z\s]{2,40}?)(?:\s*[-|,]|\s*\d|$)",
            text, re.IGNORECASE,
        )
        if cp and len(cp.group(1).strip()) >= 3:
            result["contact_person"] = cp.group(1).strip()

        ph = re.search(
            r"(?:contact|call|mobile|phone|tel|whatsapp)[:\s]*([+]?[\d][\d\s\-().]{7,14}\d)",
            text, re.IGNORECASE,
        ) or re.search(r"\b([6-9]\d{9})\b", text)
        if ph:
            phone = re.sub(r"[\s\-().]", "", ph.group(1))
            if len(phone) >= 8:
                result["contact_phone"] = phone

        return result

    def is_relevant(self, job: Dict[str, Any]) -> bool:
        haystack = " ".join([
            str(job.get("title", "")),
            str(job.get("job_description", "")),
            str(job.get("experience", "")),
        ]).lower()
        return any(kw in haystack for kw in RELEVANCE_KEYWORDS)

    @staticmethod
    def to_telegram_format(job: Dict[str, Any]) -> str:
        def _f(val, default="—"):
            return str(val).strip() if val else default

        lines = [
            f"🔥 {_f(job.get('title'))}", "",
            f"🏢 {_f(job.get('company'))}",
            f"📍 {_f(job.get('location'))}", "",
            f"💰 Salary: {_f(job.get('salary'))}",
            f"📊 Experience: {_f(job.get('experience'))}",
        ]
        if job.get("walkin_dates") or job.get("walkin_time"):
            lines += ["", "🗓 WALK-IN DETAILS:",
                      f"   {_f(job.get('walkin_dates'))}",
                      f"   {_f(job.get('walkin_time'))}"]
        if job.get("address"):
            lines += ["", "📍 Address:", f"   {_f(job.get('address'))}"]
        parts = [str(p) for p in [job.get("contact_person"), job.get("contact_phone")] if p]
        if parts:
            lines += ["", f"📞 Contact: {' | '.join(parts)}"]
        lines += ["", "🚨 JOB LINK:", f"{_f(job.get('job_url'), '#')}"]
        return "\n".join(lines)[:4096]
