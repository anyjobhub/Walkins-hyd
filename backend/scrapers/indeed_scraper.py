"""
scrapers/indeed_scraper.py — Indeed walk-in job scraper using RSS feeds.

Indeed provides public RSS feeds that are freely accessible and don't
require authentication, making this approach fully compliant.

NEW: Multi-city scraping, relevance filtering, Telegram-ready formatting.

RSS URL pattern:
  https://in.indeed.com/rss?q=walk-in+interview&l=India&sort=date
"""

from __future__ import annotations

import logging
import re
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


class IndeedScraper(BaseScraper):
    """
    Parses Indeed India job listings via their public RSS feed.

    Indeed's RSS is the preferred scraping approach — it's documented,
    freely available, and doesn't require any API key.
    """

    RSS_BASE = "https://in.indeed.com/rss"

    def __init__(self):
        super().__init__(source_name="indeed")
        self.cleaner = DataCleaner()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def scrape_jobs(
        self,
        location: str = "Hyderabad",
        keywords: str = "walk-in",
        max_pages: int = 2,
    ) -> List[Dict[str, Any]]:
        """Scrape Indeed jobs using 5 targeted queries per city."""
        search_queries = [
            "walk in interview",
            "walk-in drive",
            "fresher jobs",
            "bpo customer support",
            "walkin freshers",
        ]

        all_jobs: List[Dict] = []
        seen_urls: Set[str] = set()
        logger.info("Indeed | city=%s | running %d queries", location, len(search_queries))

        for query in search_queries:
            for page in range(max_pages):
                start = page * 10
                try:
                    jobs = self._fetch_rss(query, location, start=start)
                    if not jobs:
                        break
                    new = 0
                    for job in jobs:
                        url = job.get("job_url", "")
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
                        all_jobs.append(job)
                        new += 1
                    logger.info("Indeed | city=%s query='%s' p%d → %d jobs (%d new)",
                                location, query, page + 1, len(jobs), new)
                except Exception as exc:
                    logger.error("Indeed RSS error city=%s query='%s': %s", location, query, exc)
                    break

        logger.info("Indeed | city=%s done | total_unique=%d", location, len(all_jobs))
        return all_jobs

    def parse_job_listing(self, element: Any) -> Optional[Dict[str, Any]]:
        """
        Parse a feedparser entry from Indeed RSS into a job dict.

        Indeed RSS entries typically contain:
          - title: "Job Title - Company Name"
          - link: Job URL
          - summary: HTML snippet with job details
          - published: Posting date
          - author: Company name (in some feeds)
        """
        try:
            job = self._build_base_job()

            # Raw title is often "Job Title - Company Name"
            raw_title = getattr(element, "title", "") or ""
            if " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                job["title"] = parts[0].strip()
                job["company"] = parts[1].strip()
            else:
                job["title"] = raw_title
                job["company"] = getattr(element, "author", "Unknown") or "Unknown"

            if not job["title"]:
                return None

            # Job URL
            job["job_url"] = getattr(element, "link", "") or ""
            # Indeed job keys are embedded in the URL path
            import re
            jk_match = re.search(r"jk=([a-f0-9]+)", job["job_url"])
            job["source_id"] = jk_match.group(1) if jk_match else job["job_url"][-40:]

            # Location (often in the title suffix or tags)
            tags = getattr(element, "tags", []) or []
            location_tag = next(
                (t.term for t in tags if t.scheme and "location" in t.scheme.lower()),
                None,
            )
            job["location"] = location_tag or ""

            # Summary / description (HTML — we strip tags)
            summary_html = (
                getattr(element, "summary", "") or
                getattr(element, "description", "") or ""
            )
            # Strip HTML tags for text processing
            from bs4 import BeautifulSoup as BS
            summary_text = BS(summary_html, "html.parser").get_text(
                separator=" ", strip=True
            )
            job["job_description"] = summary_text

            # Extract location from summary if not in tags
            if not job["location"]:
                loc_match = re.search(
                    r"Location[:\s]+([A-Za-z ,]+?)(?:\n|<|$)", summary_text
                )
                if loc_match:
                    job["location"] = loc_match.group(1).strip()

            # Posted date
            published = getattr(element, "published_parsed", None)
            if published:
                from datetime import datetime, timezone
                job["posted_date"] = datetime(*published[:6], tzinfo=timezone.utc)

            # Salary extraction from description
            salary_match = re.search(
                r"(?:salary|pay|ctc)[:\s]+([₹$]?[\d,.\s]+(?:lakh|LPA|lac|k|K)?(?:\s*[-–]\s*[₹$]?[\d,.\s]+(?:lakh|LPA|lac|k|K)?)?)",
                summary_text,
                re.IGNORECASE,
            )
            if salary_match:
                job["salary"] = salary_match.group(1).strip()
                sal_parsed = self.cleaner.normalize_salary(job["salary"])
                job.update(sal_parsed)

            # Experience extraction from description
            exp_match = re.search(
                r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience)?",
                summary_text,
                re.IGNORECASE,
            )
            if exp_match:
                job["experience"] = exp_match.group(0).strip()
                exp_parsed = self.cleaner.normalize_experience(job["experience"])
                job.update(exp_parsed)

            # Walk-in and fresher detection
            combined = f"{job['title']} {summary_text}"
            job["is_walkin"] = self._detect_walkin(combined)
            job["is_fresher_friendly"] = self._detect_fresher(combined)

            # UPGRADED: always extract walk-in details (not just when is_walkin)
            walkin_info = self.extract_walkin_details(summary_text)
            for key, val in walkin_info.items():
                if val and not job.get(key):
                    job[key] = val

            return job

        except Exception as exc:
            logger.debug("Failed to parse Indeed entry: %s", exc)
            return None

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _fetch_rss(
        self, keywords: str, location: str, start: int = 0
    ) -> List[Dict[str, Any]]:
        """Fetch and parse Indeed's RSS feed."""
        params = {
            "q": keywords,
            "l": location,
            "sort": "date",
            "fromage": "3",   # Jobs from last 3 days (not 1 — too restrictive)
            "start": start,
        }
        url = f"{self.RSS_BASE}?{urlencode(params)}"
        logger.info("Indeed RSS fetching: %s", url)

        feed = feedparser.parse(
            url,
            request_headers={
                "User-Agent": self._random_user_agent(),
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
        )

        if feed.bozo and not feed.entries:
            logger.warning("Indeed RSS returned malformed/empty feed for '%s'", keywords)
            return []

        logger.debug("Indeed RSS: %d entries", len(feed.entries))

        jobs = []
        for entry in feed.entries:
            parsed = self.parse_job_listing(entry)
            if parsed and parsed.get("title"):
                jobs.append(parsed)

        return jobs

    # ── NEW: Improved walk-in detail extractor ────────────────────────────────
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

    # ── NEW: Relevance filter ─────────────────────────────────────────────────
    def is_relevant(self, job: Dict[str, Any]) -> bool:
        """Return True if the job matches walk-in / fresher / BPO / IT keywords."""
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
        filter_relevant: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Scrape Indeed RSS across multiple cities with dedup + relevance filter.
        """
        cities = cities or DEFAULT_CITIES
        seen_urls: Set[str] = set()
        all_jobs: List[Dict[str, Any]] = []

        for city in cities:
            logger.info("━━━ Scraping Indeed | city=%-12s ━━━", city)
            try:
                city_jobs = self.scrape_jobs(
                    location=city, keywords=keywords, max_pages=max_pages
                )
            except Exception as exc:
                logger.error("Failed scraping Indeed for %s: %s", city, exc)
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

            logger.info(
                "Indeed | city=%-12s scraped=%d  added=%d",
                city, len(city_jobs), new_count,
            )

        logger.info("Indeed scrape_all_cities done. total_unique=%d", len(all_jobs))
        return all_jobs

    # ── NEW: Telegram formatter ───────────────────────────────────────────────
    @staticmethod
    def to_telegram_format(job: Dict[str, Any]) -> str:
        """Format a job dict as a Telegram-ready plain-text message."""
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
                "", "🗓 WALK-IN DETAILS:",
                f"   {_f(job.get('walkin_dates'))}",
                f"   {_f(job.get('walkin_time'))}",
            ]
        if job.get("address"):
            lines += ["", "📍 Address:", f"   {_f(job.get('address'))}"]
        contact_parts = [
            p for p in [job.get("contact_person"), job.get("contact_phone")] if p
        ]
        if contact_parts:
            lines.append(f"\n📞 Contact: {' | '.join(str(p) for p in contact_parts)}")
        lines += ["", "🚨 JOB LINK:", f"{_f(job.get('job_url'), '#')}"]
        return "\n".join(lines)[:4096]
