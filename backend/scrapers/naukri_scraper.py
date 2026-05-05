"""
scrapers/naukri_scraper.py — Naukri.com walk-in job scraper.

Strategy:
  - Uses Naukri's public search URL with BeautifulSoup HTML parsing.
  - Respects 2-4 second delays and robots.txt.
  - Falls back gracefully if HTML structure changes.
  - NEW: Multi-city scraping, relevance filtering, Telegram formatting.

COMPLIANCE NOTE:
  Naukri's ToS restricts automated scraping. This implementation
  uses polite delays, respects robots.txt, and should be used only
  for personal/educational purposes. Always review Naukri ToS before
  running in production.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, ForbiddenError, RateLimitError
from services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

# ── Cities to scrape by default ───────────────────────────────────────────────
DEFAULT_CITIES: List[str] = ["Hyderabad", "Bangalore", "Chennai"]

# ── Keywords that make a job relevant to our audience ─────────────────────────
RELEVANCE_KEYWORDS: List[str] = [
    # Walk-in signals
    "walk-in", "walkin", "walk in", "direct interview", "spot interview",
    "open interview", "open house",
    # Fresher signals
    "fresher", "freshers", "0 experience", "0-1 year", "entry level",
    "trainee", "graduate",
    # Domain signals
    "bpo", "voice", "customer support", "customer care", "call center",
    "non-it", "non it", "it support", "helpdesk", "data entry",
    "back office", "operations",
]


class NaukriScraper(BaseScraper):
    """Scrapes walk-in job listings from Naukri.com."""

    BASE_URL = "https://www.naukri.com"
    SEARCH_PATH = "/jobs-listings"

    def __init__(self):
        super().__init__(source_name="naukri")
        self.cleaner = DataCleaner()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def scrape_jobs(
        self,
        location: str = "India",
        keywords: str = "walk-in interview",
        max_pages: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Scrape walk-in jobs from Naukri.

        Returns a list of job dicts that can be inserted into the DB.
        """
        all_jobs: List[Dict] = []
        logger.info(
            "Starting Naukri scrape | location=%s keywords=%s max_pages=%d",
            location, keywords, max_pages,
        )

        for page in range(1, max_pages + 1):
            try:
                page_jobs = self._scrape_page(keywords, location, page)
                if not page_jobs:
                    logger.info("No more results on page %d — stopping", page)
                    break
                all_jobs.extend(page_jobs)
                logger.info(
                    "Naukri page %d: found %d jobs (total so far: %d)",
                    page, len(page_jobs), len(all_jobs),
                )
            except (RateLimitError, ForbiddenError) as exc:
                logger.error("Naukri scrape aborted: %s", exc)
                break
            except Exception as exc:
                logger.error("Error on Naukri page %d: %s", page, exc, exc_info=True)
                continue

        logger.info("Naukri scrape complete. Total jobs: %d", len(all_jobs))
        return all_jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        """Parse a single BeautifulSoup job card element."""
        try:
            job = self._build_base_job()

            # Title
            title_el = (
                element.select_one("a.title") or
                element.select_one(".jobTitle") or
                element.select_one("[class*='title']")
            )
            if not title_el:
                return None
            job["title"] = title_el.get_text(strip=True)

            # Job URL
            href = title_el.get("href", "")
            if href:
                job["job_url"] = href if href.startswith("http") else urljoin(self.BASE_URL, href)
                # Use URL path as source_id
                job["source_id"] = re.sub(r"[?#].*", "", href).strip("/").split("/")[-1]

            # Company
            company_el = (
                element.select_one("a.comp-name") or
                element.select_one(".companyInfo a") or
                element.select_one("[class*='company']")
            )
            job["company"] = company_el.get_text(strip=True) if company_el else "Unknown"

            # Location
            loc_el = (
                element.select_one("li.location") or
                element.select_one(".locWdth") or
                element.select_one("[class*='location']")
            )
            if loc_el:
                job["location"] = loc_el.get_text(strip=True)

            # Experience
            exp_el = (
                element.select_one("li.experience") or
                element.select_one(".experience") or
                element.select_one("[class*='experience']")
            )
            if exp_el:
                job["experience"] = exp_el.get_text(strip=True)
                exp_parsed = self.cleaner.normalize_experience(job["experience"])
                job.update(exp_parsed)

            # Salary
            sal_el = (
                element.select_one("li.salary") or
                element.select_one(".salary") or
                element.select_one("[class*='salary']")
            )
            if sal_el:
                job["salary"] = sal_el.get_text(strip=True)
                sal_parsed = self.cleaner.normalize_salary(job["salary"])
                job.update(sal_parsed)

            # Tags / Skills (shown as pills in listing)
            skills_els = element.select("li.tag, .tags li, [class*='skill']")
            if skills_els:
                job["skills"] = self.cleaner.clean_skills_array(
                    ", ".join(el.get_text(strip=True) for el in skills_els)
                )

            # Description snippet (used for walk-in / fresher detection)
            desc_el = element.select_one(".job-description, [class*='desc']")
            snippet = desc_el.get_text(strip=True) if desc_el else ""

            combined_text = f"{job['title']} {snippet} {job.get('location', '')}"
            job["is_walkin"] = self._detect_walkin(combined_text)
            job["is_fresher_friendly"] = self._detect_fresher(
                f"{job['title']} {job.get('experience', '')} {snippet}"
            )

            return job

        except Exception as exc:
            logger.debug("Failed to parse Naukri job element: %s", exc)
            return None

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _build_search_url(self, keywords: str, location: str, page: int) -> str:
        """Build a Naukri search URL for walk-in jobs."""
        # Naukri uses a URL path pattern like /walk-in-jobs-in-delhi-1
        kw_slug = keywords.lower().replace(" ", "-")
        loc_slug = location.lower().replace(" ", "-")
        return f"{self.BASE_URL}/{kw_slug}-jobs-in-{loc_slug}-{page}"

    def _scrape_page(
        self, keywords: str, location: str, page: int
    ) -> List[Dict[str, Any]]:
        """Fetch and parse a single results page."""
        url = self._build_search_url(keywords, location, page)
        response = self._get(url, check_robots=True)

        if not response:
            return []

        soup = BeautifulSoup(response.text, "lxml")

        # Naukri wraps job cards in various selectors depending on the page type
        job_cards = (
            soup.select("article.jobTuple") or
            soup.select(".srp-jobtuple-wrapper") or
            soup.select("[class*='jobTuple']") or
            soup.select(".job-tuple")
        )

        if not job_cards:
            logger.debug("No job cards found on Naukri page %d", page)
            return []

        jobs = []
        for card in job_cards:
            parsed = self.parse_job_listing(card)
            if parsed and parsed.get("title") and parsed.get("company"):
                jobs.append(parsed)

        return jobs

    def fetch_full_job_description(self, job_url: str) -> Optional[str]:
        """
        Fetch the full job description page to extract walk-in details
        that are not shown in the listing snippet.

        Returns the description text or None on failure.
        """
        if not job_url:
            return None

        response = self._get(job_url, check_robots=True)
        if not response:
            return None

        soup = BeautifulSoup(response.text, "lxml")

        desc_el = (
            soup.select_one(".job-desc") or
            soup.select_one("#job-description") or
            soup.select_one("[class*='description']") or
            soup.select_one(".jd-desc")
        )
        return desc_el.get_text(separator="\n", strip=True) if desc_el else None

    def enrich_with_walkin_details(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch the full description page and extract walk-in details.

        UPGRADED: always enriches if job_url is present; also extracts
        contact info and re-checks relevance signals from full text.
        """
        if not job.get("job_url"):
            return job

        desc = self.fetch_full_job_description(job["job_url"])
        if not desc:
            return job

        job["job_description"] = desc

        # Re-detect flags from full description
        job["is_walkin"] = self._detect_walkin(desc) or job.get("is_walkin", False)
        job["is_fresher_friendly"] = (
            self._detect_fresher(desc) or job.get("is_fresher_friendly", False)
        )

        # Extract structured walk-in info using the improved extractor
        walkin_info = self.extract_walkin_details(desc)
        for key, val in walkin_info.items():
            if val and not job.get(key):   # don't overwrite existing data
                job[key] = val

        return job

    # ── NEW: Improved walk-in detail extractor ────────────────────────────────
    def extract_walkin_details(self, text: str) -> Dict[str, Any]:
        """
        Extract structured walk-in fields from raw job description text.

        Handles messy real-world formats like:
          "Walk-in on 15th & 16th March, 10 AM to 5 PM"
          "Date: 20-21 April | Venue: XYZ building, MG Road"
          "Contact HR: Priya - 9876543210"

        Returns dict with keys: walkin_dates, walkin_time, address,
                                contact_person, contact_phone.
        """
        result: Dict[str, Any] = {
            "walkin_dates": None,
            "walkin_time": None,
            "address": None,
            "contact_person": None,
            "contact_phone": None,
        }
        if not text:
            return result

        # ── Dates ────────────────────────────────────────────────────────────
        MONTHS = (
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?"
            r"|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?"
            r"|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        )
        date_patterns = [
            # "15th & 16th March 2024" or "15-16 April"
            rf"(\d{{1,2}}(?:st|nd|rd|th)?\s*(?:[&,and/-]+\s*\d{{1,2}}(?:st|nd|rd|th)?\s*)?{MONTHS}(?:\s+\d{{4}})?)",
            # "Date: 20 April 2024" / "Interview Date: ..."
            rf"(?:walk[- ]?in\s+)?date[s]?[:\s]+([\w\s,&/-]{{5,40}})",
            # "March 15, 2024"
            rf"({MONTHS}\s+\d{{1,2}}(?:,\s*\d{{4}})?)",
        ]
        for pat in date_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result["walkin_dates"] = m.group(1).strip()
                break

        # ── Time ─────────────────────────────────────────────────────────────
        time_match = re.search(
            r"(?:time|timing)[:\s]*"
            r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*(?:[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))?)",
            text, re.IGNORECASE,
        )
        if not time_match:
            # bare time range without label
            time_match = re.search(
                r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))",
                text, re.IGNORECASE,
            )
        if time_match:
            result["walkin_time"] = time_match.group(1).strip()

        # ── Address / Venue ───────────────────────────────────────────────────
        venue_match = re.search(
            r"(?:venue|address|location|walk[- ]?in\s+at|office(?:\s+address)?)[:\s]+([^\n.]{10,200})",
            text, re.IGNORECASE,
        )
        if venue_match:
            result["address"] = venue_match.group(1).strip()

        # ── Contact person ────────────────────────────────────────────────────
        contact_person_match = re.search(
            r"(?:contact(?:\s+person)?|hr\s+(?:name|contact)|reach\s+(?:out\s+to)?|speak\s+to)[:\s]+"
            r"([A-Za-z][A-Za-z\s]{2,40}?)(?:\s*[-|,]|\s*\d|$)",
            text, re.IGNORECASE,
        )
        if contact_person_match:
            name = contact_person_match.group(1).strip()
            if len(name) >= 3:
                result["contact_person"] = name

        # ── Phone number ──────────────────────────────────────────────────────
        phone_match = re.search(
            r"(?:contact|call|mobile|phone|tel|whatsapp)[:\s]*"
            r"([+]?[\d][\d\s\-().]{7,14}\d)",
            text, re.IGNORECASE,
        )
        if not phone_match:
            # standalone 10-digit Indian mobile
            phone_match = re.search(r"\b([6-9]\d{9})\b", text)
        if phone_match:
            phone = re.sub(r"[\s\-().]", "", phone_match.group(1))
            if len(phone) >= 8:
                result["contact_phone"] = phone

        return result

    # ── NEW: Relevance filter ─────────────────────────────────────────────────
    def is_relevant(self, job: Dict[str, Any]) -> bool:
        """
        Return True if the job is relevant to walk-in / fresher / BPO / IT audience.

        Checks title + job_description (case-insensitive).
        """
        haystack = " ".join([
            str(job.get("title", "")),
            str(job.get("job_description", "")),
            str(job.get("experience", "")),
        ]).lower()
        return any(kw in haystack for kw in RELEVANCE_KEYWORDS)

    # ── NEW: Multi-city orchestrator ──────────────────────────────────────────
    def scrape_all_cities(
        self,
        cities: List[str] = None,
        keywords: str = "walk-in interview",
        max_pages: int = 2,
        enrich: bool = True,
        filter_relevant: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Scrape walk-in jobs across multiple cities.

        Args:
            cities:          List of city names. Defaults to DEFAULT_CITIES.
            keywords:        Search keywords.
            max_pages:       Pages per city.
            enrich:          Fetch full description for walk-in date extraction.
            filter_relevant: Only return jobs matching RELEVANCE_KEYWORDS.

        Returns:
            Deduplicated list of job dicts ready for DB + Telegram.
        """
        cities = cities or DEFAULT_CITIES
        seen_urls: Set[str] = set()
        all_jobs: List[Dict[str, Any]] = []

        for city in cities:
            logger.info("━━━ Scraping Naukri | city=%-12s keywords=%s ━━━", city, keywords)
            try:
                city_jobs = self.scrape_jobs(
                    location=city, keywords=keywords, max_pages=max_pages
                )
            except Exception as exc:
                logger.error("Failed scraping Naukri for %s: %s", city, exc)
                continue

            new_count = 0
            for job in city_jobs:
                url = job.get("job_url", "")
                if url and url in seen_urls:
                    continue   # cross-city duplicate
                if url:
                    seen_urls.add(url)

                # Enrich with full description walk-in details
                if enrich:
                    job = self.enrich_with_walkin_details(job)

                # Relevance filter
                if filter_relevant and not self.is_relevant(job):
                    logger.debug("Skipping irrelevant job: %s", job.get("title"))
                    continue

                all_jobs.append(job)
                new_count += 1

            logger.info(
                "Naukri | city=%-12s total_scraped=%d  added_after_filter=%d",
                city, len(city_jobs), new_count,
            )

        logger.info(
            "Naukri scrape_all_cities done. cities=%s  total_unique=%d",
            cities, len(all_jobs),
        )
        return all_jobs

    # ── NEW: Telegram formatter ───────────────────────────────────────────────
    @staticmethod
    def to_telegram_format(job: Dict[str, Any]) -> str:
        """
        Format a job dict into a Telegram-ready message string.

        Uses plain text (no HTML) for maximum compatibility.
        Fields that are missing are replaced with a dash.
        """
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
            lines += [
                "",
                "🗓 WALK-IN DETAILS:",
                f"   {_f(job.get('walkin_dates'))}",
                f"   {_f(job.get('walkin_time'))}",
            ]

        if job.get("address"):
            lines += ["", "📍 Address:", f"   {_f(job.get('address'))}"],

        contact_parts = []
        if job.get("contact_person"):
            contact_parts.append(_f(job.get("contact_person")))
        if job.get("contact_phone"):
            contact_parts.append(_f(job.get("contact_phone")))
        if contact_parts:
            lines.append(f"\n📞 Contact: {' | '.join(contact_parts)}")

        lines += [
            "",
            f"🚨 JOB LINK:",
            f"{_f(job.get('job_url'), '#')}",
        ]

        msg = "\n".join(lines)
        return msg[:4096]   # Telegram hard limit
