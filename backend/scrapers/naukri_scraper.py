"""
scrapers/naukri_scraper.py — Naukri.com walk-in job scraper.

Strategy:
  - Uses Naukri's internal JSON API — no HTML parsing, no JS rendering needed.
  - Multi-city scraping: Hyderabad, Bangalore, Chennai.
  - Relevance filtering for walk-in / fresher / BPO jobs.
  - Auto-deduplication by job URL across cities.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

from scrapers.base_scraper import BaseScraper, ForbiddenError, RateLimitError
from services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

# ── Cities to scrape ──────────────────────────────────────────────────────────
DEFAULT_CITIES: List[str] = ["hyderabad", "bangalore", "chennai"]

# ── Naukri JSON API ───────────────────────────────────────────────────────────
NAUKRI_API   = "https://www.naukri.com/jobapi/v3/search"
NAUKRI_BASE  = "https://www.naukri.com"

# Required headers for Naukri's API to return JSON (not HTML)
NAUKRI_HEADERS = {
    "appid":        "109",
    "systemId":     "109",
    "Accept":       "application/json",
    "Content-Type": "application/json",
    "Origin":       "https://www.naukri.com",
    "Referer":      "https://www.naukri.com/",
    "User-Agent":   (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# ── Relevance keywords ────────────────────────────────────────────────────────
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
    """Scrapes walk-in job listings from Naukri.com via their JSON API."""

    BASE_URL = NAUKRI_BASE

    def __init__(self):
        super().__init__(source_name="naukri")
        self.cleaner = DataCleaner()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API (keeps BaseScraper interface)
    # ─────────────────────────────────────────────────────────────────────────
    def scrape_jobs(
        self,
        location: str = "hyderabad",
        keywords: str = "walk-in interview",
        max_pages: int = 2,
    ) -> List[Dict[str, Any]]:
        """Scrape walk-in jobs for a single city via Naukri JSON API."""
        all_jobs: List[Dict] = []
        logger.info("Naukri | city=%-12s pages=%d", location, max_pages)

        for page in range(1, max_pages + 1):
            try:
                page_jobs = self._fetch_api_page(keywords, location, page)
                if not page_jobs:
                    logger.info("Naukri | city=%s page=%d → 0 results, stopping", location, page)
                    break
                all_jobs.extend(page_jobs)
                logger.info("Naukri | city=%s page=%d → %d jobs (total %d)",
                            location, page, len(page_jobs), len(all_jobs))
            except (RateLimitError, ForbiddenError) as exc:
                logger.error("Naukri aborted for %s: %s", location, exc)
                break
            except Exception as exc:
                logger.error("Naukri page error city=%s page=%d: %s", location, page, exc)
                continue

        return all_jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        """Parse a raw Naukri API job dict into our standard format."""
        try:
            job = self._build_base_job()

            job["title"] = element.get("jobTitle", "").strip()
            if not job["title"]:
                return None

            job["company"] = element.get("companyName", "Unknown").strip()

            # Job URL
            jd_url = element.get("jdURL", "")
            if jd_url:
                job["job_url"] = (
                    jd_url if jd_url.startswith("http")
                    else urljoin(NAUKRI_BASE, jd_url)
                )
                job["source_id"] = jd_url.strip("/").split("/")[-1].split("?")[0]

            # Placeholders: location / experience / salary
            for ph in element.get("placeholders", []):
                ph_type  = ph.get("type", "")
                ph_label = ph.get("label", "").strip()
                if not ph_label:
                    continue
                if ph_type == "location":
                    job["location"] = ph_label
                elif ph_type == "experience":
                    job["experience"] = ph_label
                    job.update(self.cleaner.normalize_experience(ph_label))
                elif ph_type == "salary":
                    job["salary"] = ph_label
                    job.update(self.cleaner.normalize_salary(ph_label))

            # Skills / tags
            tags = element.get("tagsAndSkills", "")
            if tags:
                job["skills"] = self.cleaner.clean_skills_array(tags)

            # Description snippet (from listing)
            snippet = element.get("jobDescription", "").strip()
            job["job_description"] = snippet

            # Walk-in / fresher detection
            combined = f"{job['title']} {snippet} {job.get('location', '')}"
            job["is_walkin"]          = self._detect_walkin(combined)
            job["is_fresher_friendly"] = self._detect_fresher(combined)

            return job

        except Exception as exc:
            logger.debug("Failed to parse Naukri job item: %s", exc)
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Multi-city orchestrator
    # ─────────────────────────────────────────────────────────────────────────
    def scrape_all_cities(
        self,
        cities: List[str] = None,
        keywords: str = "walk-in interview",
        max_pages: int = 2,
        enrich: bool = False,        # enriching via full-page fetch is slow; skip by default
        filter_relevant: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Scrape walk-in jobs across Hyderabad, Bangalore, Chennai.
        Deduplicates by job URL across cities.
        """
        cities = cities or DEFAULT_CITIES
        seen_urls: Set[str] = set()
        all_jobs: List[Dict[str, Any]] = []

        for city in cities:
            logger.info("━━━ Naukri | city=%-12s ━━━", city)
            try:
                city_jobs = self.scrape_jobs(location=city, keywords=keywords, max_pages=max_pages)
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

                if enrich:
                    job = self.enrich_with_walkin_details(job)

                if filter_relevant and not self.is_relevant(job):
                    logger.debug("Filtered out: %s", job.get("title"))
                    continue

                all_jobs.append(job)
                added += 1

            logger.info("Naukri | city=%-12s scraped=%d  kept=%d", city, len(city_jobs), added)

        logger.info("Naukri scrape_all_cities done | cities=%s total=%d", cities, len(all_jobs))
        return all_jobs

    # ─────────────────────────────────────────────────────────────────────────
    # Internal: JSON API fetcher
    # ─────────────────────────────────────────────────────────────────────────
    def _fetch_api_page(
        self, keyword: str, location: str, page: int
    ) -> List[Dict[str, Any]]:
        """Call Naukri's JSON search API for one page."""
        params = {
            "noOfResults":  20,
            "urlType":      "search_by_keyword",
            "searchType":   "adv",
            "keyword":      keyword,
            "location":     location,
            "pageNo":       page,
            "seoKey":       f"walkin-jobs-in-{location}",
        }
        api_url = NAUKRI_API
        logger.info("Naukri API GET %s?keyword=%s&location=%s&pageNo=%d",
                    api_url, keyword, location, page)

        response = self._get(api_url, params=params, headers=NAUKRI_HEADERS, check_robots=False)
        if not response:
            logger.warning("Naukri API returned no response for city=%s page=%d", location, page)
            return []

        # Check if response is JSON
        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            logger.warning(
                "Naukri API returned non-JSON (Content-Type: %s) for city=%s — "
                "likely blocked. First 200 chars: %s",
                content_type, location, response.text[:200],
            )
            return []

        try:
            data = response.json()
        except Exception as exc:
            logger.error("Naukri API JSON parse failed: %s | body=%s", exc, response.text[:300])
            return []

        items = data.get("jobDetails", [])
        logger.info("Naukri API | city=%s page=%d | noOfJobs=%s parsed=%d",
                    location, page, data.get("noOfJobs", "?"), len(items))

        jobs = []
        for item in items:
            parsed = self.parse_job_listing(item)
            if parsed and parsed.get("title"):
                jobs.append(parsed)
        return jobs

    # ─────────────────────────────────────────────────────────────────────────
    # Walk-in detail enrichment (optional, slow — fetches full job page)
    # ─────────────────────────────────────────────────────────────────────────
    def enrich_with_walkin_details(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch the full job page to extract walk-in date/time/venue/contact."""
        if not job.get("job_url"):
            return job
        try:
            resp = self._get(job["job_url"], check_robots=False)
            if not resp:
                return job
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")
            desc_el = (
                soup.select_one(".job-desc") or
                soup.select_one("#job-description") or
                soup.select_one("[class*='description']") or
                soup.select_one(".jd-desc")
            )
            if desc_el:
                full_text = desc_el.get_text(separator="\n", strip=True)
                job["job_description"] = full_text
                job["is_walkin"]           = self._detect_walkin(full_text) or job.get("is_walkin", False)
                job["is_fresher_friendly"] = self._detect_fresher(full_text) or job.get("is_fresher_friendly", False)
                walkin_info = self.extract_walkin_details(full_text)
                for key, val in walkin_info.items():
                    if val and not job.get(key):
                        job[key] = val
        except Exception as exc:
            logger.debug("enrich_with_walkin_details failed: %s", exc)
        return job

    # ─────────────────────────────────────────────────────────────────────────
    # Walk-in field extractor
    # ─────────────────────────────────────────────────────────────────────────
    def extract_walkin_details(self, text: str) -> Dict[str, Any]:
        """Extract walkin_dates, walkin_time, address, contact_person, contact_phone."""
        result: Dict[str, Any] = {
            "walkin_dates":   None,
            "walkin_time":    None,
            "address":        None,
            "contact_person": None,
            "contact_phone":  None,
        }
        if not text:
            return result

        MONTHS = (
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?"
            r"|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?"
            r"|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        )
        for pat in [
            rf"(\d{{1,2}}(?:st|nd|rd|th)?\s*(?:[&,and/-]+\s*\d{{1,2}}(?:st|nd|rd|th)?\s*)?{MONTHS}(?:\s+\d{{4}})?)",
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
        if cp:
            name = cp.group(1).strip()
            if len(name) >= 3:
                result["contact_person"] = name

        ph = re.search(
            r"(?:contact|call|mobile|phone|tel|whatsapp)[:\s]*([+]?[\d][\d\s\-().]{7,14}\d)",
            text, re.IGNORECASE,
        ) or re.search(r"\b([6-9]\d{9})\b", text)
        if ph:
            phone = re.sub(r"[\s\-().]", "", ph.group(1))
            if len(phone) >= 8:
                result["contact_phone"] = phone

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Relevance filter
    # ─────────────────────────────────────────────────────────────────────────
    def is_relevant(self, job: Dict[str, Any]) -> bool:
        haystack = " ".join([
            str(job.get("title", "")),
            str(job.get("job_description", "")),
            str(job.get("experience", "")),
        ]).lower()
        return any(kw in haystack for kw in RELEVANCE_KEYWORDS)

    # ─────────────────────────────────────────────────────────────────────────
    # Telegram formatter
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def to_telegram_format(job: Dict[str, Any]) -> str:
        """Format a job dict into a Telegram-ready message string."""
        def _f(val, default="—"):
            return str(val).strip() if val else default

        lines = [
            f"🔥 {_f(job.get('title'))}",
            "",
            f"🏢 {_f(job.get('company'))}",
            f"📍 {_f(job.get('location'))}",
            "",
            f"💰 Salary: {_f(job.get('salary'))}",
            f"📊 Experience: {_f(job.get('experience'))}",
        ]
        if job.get("walkin_dates") or job.get("walkin_time"):
            lines += ["", "🗓 WALK-IN DETAILS:",
                      f"   {_f(job.get('walkin_dates'))}",
                      f"   {_f(job.get('walkin_time'))}"]
        if job.get("address"):
            lines += ["", "📍 Address:", f"   {_f(job.get('address'))}"]
        parts = [_f(p) for p in [job.get("contact_person"), job.get("contact_phone")] if p]
        if parts:
            lines += ["", f"📞 Contact: {' | '.join(parts)}"]
        lines += ["", "🚨 JOB LINK:", f"{_f(job.get('job_url'), '#')}"]

        return "\n".join(lines)[:4096]
