"""
utils/validators.py — Input validation functions used across the application.
"""

from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import urlparse


def is_valid_url(url: str) -> bool:
    """Return True if url is a valid HTTP/HTTPS URL."""
    if not url or not isinstance(url, str):
        return False
    try:
        result = urlparse(url)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


def is_valid_phone(phone: str) -> bool:
    """
    Return True if phone looks like a valid Indian mobile/landline number.

    Accepts:
      - 10-digit mobiles: 9876543210
      - With country code: +919876543210, 0091...
    """
    if not phone:
        return False
    cleaned = re.sub(r"[\s\-().]", "", str(phone))
    # Remove leading +91 or 0091
    cleaned = re.sub(r"^(\+91|0091|91)", "", cleaned)
    # Validate 10-digit Indian mobile (starts with 6-9)
    return bool(re.match(r"^[6-9]\d{9}$", cleaned))


def is_valid_email(email: str) -> bool:
    """Return True if email is a valid email address (basic check)."""
    if not email:
        return False
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, str(email).strip()))


def is_walkin_job(job: Dict[str, Any]) -> bool:
    """
    Determine if a job dict represents a walk-in interview.

    Checks:
      1. is_walkin flag already set by scraper
      2. Walk-in keywords in title or description
      3. Has walkin_dates field populated
    """
    if job.get("is_walkin"):
        return True

    if job.get("walkin_dates"):
        return True

    text = " ".join([
        str(job.get("title", "")),
        str(job.get("job_description", "")),
        str(job.get("walkin_dates", "")),
    ]).lower()

    walkin_keywords = [
        "walk-in", "walkin", "walk in", "direct interview",
        "spot interview", "open interview", "open house",
    ]
    return any(kw in text for kw in walkin_keywords)


def sanitize_string(value: str, max_length: int = 255) -> str:
    """Strip and truncate a string. Returns empty string for None."""
    if not value:
        return ""
    return str(value).strip()[:max_length]


def sanitize_job_dict(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize all string fields in a job dict to prevent injection.
    """
    string_fields = [
        "title", "company", "location", "salary", "experience",
        "walkin_dates", "walkin_time", "address", "contact_person",
        "contact_phone", "contact_email",
    ]
    for field in string_fields:
        if field in job and job[field]:
            job[field] = sanitize_string(job[field])

    # URL fields — validate
    for url_field in ("job_url",):
        if job.get(url_field) and not is_valid_url(job[url_field]):
            job[url_field] = None

    return job
