"""
scrapers/linkedin_scraper.py — LinkedIn walk-in job scraper using RSS feeds.

Strategy:
  - Uses LinkedIn's public RSS feed for job searches.
  - Multi-city scraping: Hyderabad, Bangalore, Chennai.
  - Targeted queries as requested by user.
  - Retry logic for empty feeds.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

import feedparser

from scrapers.base_scraper import BaseScraper
from services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

# ── Shared constants ─────────────────────────────────────────────────────────
DEFAULT_CITIES: List[str] = ["Hyderabad", "Bangalore", "Chennai"]

RELEVANCE_KEYWORDS: List[str] = [
    "walk-in", "walkin", "walk in", "direct interview", "spot interview",
    "open interview", "open house",
    "fresher", "freshers", "0 experience", "0-1 year", "entry level",
    "trainee", "graduate",
    "bpo", "voice", "customer support", "customer care", "call center",
    "non-it", "non it", "it support", "helpdesk", "data entry",
    "back office", "operations",
]


class LinkedInScraper(BaseScraper):
    """Parses LinkedIn job listings via their public RSS/Atom feed."""

    BASE_URL = "https://www.linkedin.com/jobs/search/"

    def __init__(self):
        super().__init__(source_name="linkedin")
        self.cleaner = DataCleaner()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def scrape_jobs(
        self,
        location: str = "Hyderabad",
        keywords: str = "walk-in",
        max_pages: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Fetch LinkedIn job listings using multiple targeted RSS queries as requested.
        """
        # Targeted queries per city as requested by user
        search_queries = [
            f"walk in {location}",
            f"walk-in drive {location}",
            f"fresher jobs {location}",
            f"bpo jobs {location}",
            "customer support executive",
        ]

        all_jobs: List[Dict] = []
        seen_urls: Set[str] = set()

        logger.info("LinkedIn | city=%s | running %d queries", location, len(search_queries))

        for query in search_queries:
            try:
                jobs = self._fetch_rss(query, location)
                # Retry if feed empty as requested
                if not jobs:
                    logger.info("LinkedIn | Feed empty for query '%s', retrying...", query)
                    time.sleep(2)
                    jobs = self._fetch_rss(query, location)

                new_count = 0
                for job in jobs:
                    url = job.get("job_url", "")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    all_jobs.append(job)
                    new_count += 1
                logger.info("LinkedIn | city=%s query='%s' → %d jobs (%d new)",
                            location, query, len(jobs), new_count)
            except Exception as exc:
                logger.error("LinkedIn RSS error city=%s query='%s': %s", location, query, exc)

        if not all_jobs:
            logger.warning("LinkedIn | No jobs found for city=%s", location)

        return all_jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        """Parse a single feedparser entry into a job dict."""
        try:
            job = self._build_base_job()

            job["title"] = getattr(element, "title", "") or ""
            if not job["title"]:
                return None

            job["job_url"] = getattr(element, "link", "") or ""
            job["source_id"] = job["job_url"].split("?")[0].strip("/").split("/")[-1]

            summary = getattr(element, "summary", "") or getattr(element, "description", "") or ""
            job["job_description"] = summary

            # Extract company and location from title "Title at Company in Location"
            title_parts = job["title"].split(" at ")
            if len(title_parts) >= 2:
                job["title"] = title_parts[0].strip()
                company_location = title_parts[1]
                loc_parts = company_location.split(" in ")
                job["company"] = loc_parts[0].strip()
                if len(loc_parts) >= 2:
                    job["location"] = loc_parts[1].strip()
            else:
                tags = getattr(element, "tags", []) or []
                job["company"] = next((t.term for t in tags if t.scheme and "company" in t.scheme), "Unknown")

            published = getattr(element, "published_parsed", None)
            if published:
                from datetime import datetime, timezone
                job["posted_date"] = datetime(*published[:6], tzinfo=timezone.utc)

            combined = f"{job['title']} {summary}"
            job["is_walkin"] = self._detect_walkin(combined)
            job["is_fresher_friendly"] = self._detect_fresher(combined)

            if summary:
                walkin_info = self.extract_walkin_details(summary)
                for key, val in walkin_info.items():
                    if val and not job.get(key):
                        job[key] = val

            return job

        except Exception as exc:
            logger.debug("Failed to parse LinkedIn entry: %s", exc)
            return None

    def _fetch_rss(self, keywords: str, location: str) -> List[Dict[str, Any]]:
        """Fetch and parse the LinkedIn RSS feed."""
        params = {
            "keywords": keywords,
            "location": location,
            "rss": "1",
            "f_TPR": "r86400",    # Last 24 hours
        }
        url = f"{self.BASE_URL}?{urlencode(params)}"

        self._sleep_between_requests()
        logger.debug("Fetching LinkedIn RSS: %s", url)

        feed = feedparser.parse(
            url,
            request_headers={
                "User-Agent": self._random_user_agent(),
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
        )

        if feed.bozo and not feed.entries:
            return []

        jobs = []
        for entry in feed.entries:
            parsed = self.parse_job_listing(entry)
            if parsed and parsed.get("title"):
                jobs.append(parsed)

        return jobs

    def extract_walkin_details(self, text: str) -> Dict[str, Any]:
        """Extract structured walk-in fields from raw description text."""
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
            r"(?:venue|address|location|office(?:\s+address)?)[:\s]+([^\n.]{10,200})",
            text, re.IGNORECASE,
        )
        if vm:
            result["address"] = vm.group(1).strip()

        cpm = re.search(
            r"(?:contact(?:\s+person)?|hr\s+(?:name|contact)|reach\s+to)[:\s]+"
            r"([A-Za-z][A-Za-z\s]{2,40}?)(?:\s*[-|,]|\s*\d|$)",
            text, re.IGNORECASE,
        )
        if cpm and len(cpm.group(1).strip()) >= 3:
            result["contact_person"] = cpm.group(1).strip()

        pm = re.search(
            r"(?:contact|call|mobile|phone|tel|whatsapp)[:\s]*([+]?[\d][\d\s\-().]{7,14}\d)",
            text, re.IGNORECASE,
        ) or re.search(r"\b([6-9]\d{9})\b", text)
        if pm:
            phone = re.sub(r"[\s\-().]", "", pm.group(1))
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

    def scrape_all_cities(
        self,
        cities: List[str] = None,
        keywords: str = "walk-in",
        max_pages: int = 2,
        filter_relevant: bool = True,
    ) -> List[Dict[str, Any]]:
        """Scrape LinkedIn RSS across Hyderabad, Bangalore, Chennai."""
        cities = cities or DEFAULT_CITIES
        seen_urls: Set[str] = set()
        all_jobs: List[Dict[str, Any]] = []

        for city in cities:
            logger.info("━━━ LinkedIn | city=%-12s ━━━", city)
            try:
                city_jobs = self.scrape_jobs(location=city, keywords=keywords)
                if not city_jobs:
                    logger.warning("LinkedIn | No jobs found for city=%s, continuing to next city", city)
            except Exception as exc:
                logger.error("LinkedIn failed for city=%s: %s", city, exc)
                continue

            new_count = 0
            for job in city_jobs:
                url = job.get("job_url", "")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                if filter_relevant and not self.is_relevant(job):
                    continue
                all_jobs.append(job)
                new_count += 1

            logger.info("LinkedIn | city=%-12s scraped=%d  added=%d", city, len(city_jobs), new_count)

        logger.info("LinkedIn scrape_all_cities done. total_unique=%d", len(all_jobs))
        return all_jobs

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
        contact_parts = [p for p in [job.get("contact_person"), job.get("contact_phone")] if p]
        if contact_parts:
            lines.append(f"\n📞 Contact: {' | '.join(str(p) for p in contact_parts)}")
        lines += ["", "🚨 JOB LINK:", f"{_f(job.get('job_url'), '#')}"]
        return "\n".join(lines)[:4096]
