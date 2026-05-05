"""
services/data_cleaner.py — Data normalization and cleaning for job records.

All functions are pure (no DB access) and can be tested independently.
"""

from __future__ import annotations

import re
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# City normalization master list
# Maps various spellings/aliases → canonical city name
# =============================================================================
CITY_ALIASES: Dict[str, str] = {
    # NCR
    "delhi": "Delhi", "new delhi": "Delhi", "delhi ncr": "NCR",
    "ncr": "NCR", "noida": "Noida", "gurgaon": "Gurugram",
    "gurugram": "Gurugram", "faridabad": "Faridabad", "ghaziabad": "Ghaziabad",
    # Maharashtra
    "mumbai": "Mumbai", "bombay": "Mumbai", "navi mumbai": "Navi Mumbai",
    "thane": "Thane", "pune": "Pune", "poona": "Pune", "nagpur": "Nagpur",
    "nashik": "Nashik",
    # Karnataka
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "mysore": "Mysuru",
    "mysuru": "Mysuru", "hubli": "Hubballi",
    # Tamil Nadu
    "chennai": "Chennai", "madras": "Chennai", "coimbatore": "Coimbatore",
    "madurai": "Madurai",
    # Telangana / AP
    "hyderabad": "Hyderabad", "secunderabad": "Hyderabad",
    "visakhapatnam": "Visakhapatnam", "vizag": "Visakhapatnam",
    # West Bengal
    "kolkata": "Kolkata", "calcutta": "Kolkata",
    # Gujarat
    "ahmedabad": "Ahmedabad", "surat": "Surat", "vadodara": "Vadodara",
    "baroda": "Vadodara",
    # Rajasthan
    "jaipur": "Jaipur", "jodhpur": "Jodhpur",
    # UP
    "lucknow": "Lucknow", "kanpur": "Kanpur", "agra": "Agra",
    "varanasi": "Varanasi",
    # Punjab / Haryana
    "chandigarh": "Chandigarh", "ludhiana": "Ludhiana", "amritsar": "Amritsar",
    # Kerala
    "kochi": "Kochi", "cochin": "Kochi", "thiruvananthapuram": "Thiruvananthapuram",
    "trivandrum": "Thiruvananthapuram",
    # Other major cities
    "bhopal": "Bhopal", "indore": "Indore", "patna": "Patna",
    "bhubaneswar": "Bhubaneswar", "guwahati": "Guwahati",
    "dehradun": "Dehradun", "raipur": "Raipur",
}

# Experience level thresholds (in years)
EXPERIENCE_LEVELS: List[Tuple[float, float, str]] = [
    (0.0, 1.0, "fresher"),
    (1.0, 3.0, "junior"),
    (3.0, 7.0, "mid"),
    (7.0, 15.0, "senior"),
    (15.0, 99.0, "lead"),
]


class DataCleaner:
    """
    Normalises and cleans raw job data from scrapers.

    All methods return a dict with the relevant keys to update on the
    job record, so callers can do: job.update(cleaner.normalize_salary(...))
    """

    # -------------------------------------------------------------------------
    # Salary Normalisation
    # -------------------------------------------------------------------------
    def normalize_salary(self, salary_str: str) -> Dict[str, Any]:
        """
        Parse salary strings into min/max/currency.

        Handles:
          - "₹5-10 LPA"
          - "5 to 10 lakh"
          - "15,000 - 25,000 per month"
          - "Not Disclosed"
          - "$50k-70k"

        Returns:
            {"salary_min": int, "salary_max": int, "salary_currency": str}
        """
        result: Dict[str, Any] = {
            "salary_min": None,
            "salary_max": None,
            "salary_currency": "INR",
        }

        if not salary_str:
            return result

        s = salary_str.strip()

        # Detect currency
        if "$" in s or "usd" in s.lower():
            result["salary_currency"] = "USD"
        elif "£" in s:
            result["salary_currency"] = "GBP"
        else:
            result["salary_currency"] = "INR"

        # Remove currency symbols and clean up
        s = re.sub(r"[₹$£,]", "", s)

        # Match LPA / lakh / lac patterns (annual)
        lpa_match = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:[-–to]+\s*(\d+(?:\.\d+)?))?\s*(?:lpa|lakh|lac|l\b)",
            s,
            re.IGNORECASE,
        )
        if lpa_match:
            min_val = float(lpa_match.group(1)) * 100_000
            max_val = float(lpa_match.group(2) or lpa_match.group(1)) * 100_000
            result["salary_min"] = int(min_val)
            result["salary_max"] = int(max_val)
            return result

        # Match monthly salary (per month / pm / month)
        monthly_match = re.search(
            r"(\d+(?:,\d+)?(?:\.\d+)?)\s*(?:[-–to]+\s*(\d+(?:,\d+)?(?:\.\d+)?))?.*?(?:per\s*month|pm|monthly|/month)",
            s,
            re.IGNORECASE,
        )
        if monthly_match:
            min_val = float(monthly_match.group(1).replace(",", "")) * 12
            max_str = monthly_match.group(2)
            max_val = float(max_str.replace(",", "")) * 12 if max_str else min_val
            result["salary_min"] = int(min_val)
            result["salary_max"] = int(max_val)
            return result

        # Match k (thousands) patterns
        k_match = re.search(
            r"(\d+(?:\.\d+)?)\s*k?\s*(?:[-–to]+\s*(\d+(?:\.\d+)?)k?)?",
            s,
            re.IGNORECASE,
        )
        if k_match:
            min_val = float(k_match.group(1))
            max_val = float(k_match.group(2) or k_match.group(1))
            # If values are small (< 200), treat as thousands
            if min_val < 200:
                min_val *= 1000
                max_val *= 1000
            result["salary_min"] = int(min_val)
            result["salary_max"] = int(max_val)
            return result

        logger.debug("Could not parse salary: '%s'", salary_str)
        return result

    # -------------------------------------------------------------------------
    # Experience Normalisation
    # -------------------------------------------------------------------------
    def normalize_experience(self, exp_str: str) -> Dict[str, Any]:
        """
        Parse experience strings into min_years/max_years/level.

        Handles:
          - "3-5 years" → {min: 3, max: 5, level: "mid"}
          - "Fresher" → {min: 0, max: 1, level: "fresher"}
          - "10+ years" → {min: 10, max: None, level: "senior"}
          - "0 to 1 year" → {min: 0, max: 1, level: "fresher"}
        """
        result: Dict[str, Any] = {
            "experience_min_years": None,
            "experience_max_years": None,
            "experience_level": None,
        }

        if not exp_str:
            return result

        s = exp_str.strip().lower()

        # Fresher / no experience
        if re.search(r"\b(fresher|fresh|no exp|0\s*year)\b", s):
            result["experience_min_years"] = 0.0
            result["experience_max_years"] = 1.0
            result["experience_level"] = "fresher"
            return result

        # Range: "3-5 years" or "3 to 5 years"
        range_match = re.search(
            r"(\d+(?:\.\d+)?)\s*[-–to]+\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
            s,
        )
        if range_match:
            min_y = float(range_match.group(1))
            max_y = float(range_match.group(2))
            result["experience_min_years"] = min_y
            result["experience_max_years"] = max_y
            result["experience_level"] = self._classify_experience(min_y)
            return result

        # Single value: "5 years" or "5+ years"
        single_match = re.search(r"(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)", s)
        if single_match:
            years = float(single_match.group(1))
            result["experience_min_years"] = years
            result["experience_max_years"] = None
            result["experience_level"] = self._classify_experience(years)
            return result

        return result

    def _classify_experience(self, years: float) -> str:
        for min_y, max_y, level in EXPERIENCE_LEVELS:
            if min_y <= years < max_y:
                return level
        return "senior"

    # -------------------------------------------------------------------------
    # Location Normalisation
    # -------------------------------------------------------------------------
    def normalize_location(self, location_str: str) -> str:
        """
        Normalise a location string to a canonical city name.

        Returns the canonical name or the cleaned original if unknown.
        """
        if not location_str:
            return ""

        # Take first city if multiple are listed (e.g., "Delhi/Mumbai")
        first = re.split(r"[/|,]", location_str)[0].strip()
        key = first.lower().strip()
        return CITY_ALIASES.get(key, first.title())

    # -------------------------------------------------------------------------
    # Walk-in Date Parsing
    # -------------------------------------------------------------------------
    def parse_walkin_dates(self, text: str) -> Dict[str, Any]:
        """
        Extract walk-in date and time from job description text.

        Handles patterns like:
          - "Walk-in on 15th & 16th March 10 AM to 5 PM"
          - "Date: 20-21 April 2024, Time: 9:30 AM - 4:00 PM"
          - "Venue: ..., Contact: ..."

        Returns:
            {"walkin_dates": str, "walkin_time": str, "address": str,
             "contact_person": str, "contact_phone": str}
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

        # Date patterns
        date_patterns = [
            # "15th & 16th March" or "15-16 March 2024"
            r"(?:walk[- ]?in\s+(?:on|date[s]?)?:?\s*)?"
            r"(\d{1,2}(?:st|nd|rd|th)?\s*(?:&|and|to|-)\s*\d{1,2}(?:st|nd|rd|th)?\s+"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"(?:\s+\d{4})?)",
            # "Date: 20 April 2024"
            r"(?:date[s]?|scheduled\s+on|interview\s+date)[:\s]+([A-Za-z0-9\s,&-]+(?:\d{4})?)",
            # Simple "March 15, 2024"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"\s+\d{1,2},?\s+\d{4}",
        ]

        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["walkin_dates"] = match.group(0 if len(match.groups()) == 0 else 1).strip()
                break

        # Time patterns
        time_match = re.search(
            r"(?:time|timing[s]?)[:\s]*(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*(?:[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))?)",
            text,
            re.IGNORECASE,
        )
        if time_match:
            result["walkin_time"] = time_match.group(1).strip()
        else:
            # Try bare time range
            bare_time = re.search(
                r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))",
                text,
                re.IGNORECASE,
            )
            if bare_time:
                result["walkin_time"] = bare_time.group(1).strip()

        # Venue / Address
        venue_match = re.search(
            r"(?:venue|address|location|walk[- ]?in\s+at|office)[:\s]+([^\n.]{10,150})",
            text,
            re.IGNORECASE,
        )
        if venue_match:
            result["address"] = venue_match.group(1).strip()

        # Contact person
        contact_match = re.search(
            r"(?:contact(?:\s+person)?|hr\s+name|reach\s+(?:out\s+to)?)[:\s]+([A-Za-z\s]{3,50})",
            text,
            re.IGNORECASE,
        )
        if contact_match:
            result["contact_person"] = contact_match.group(1).strip()

        # Phone number
        phone_match = re.search(
            r"(?:contact|call|phone|mobile|tel)[:\s]*([+\d\s\-()]{8,15})",
            text,
            re.IGNORECASE,
        )
        if phone_match:
            phone = re.sub(r"[^\d+]", "", phone_match.group(1))
            if len(phone) >= 8:
                result["contact_phone"] = phone

        return result

    # -------------------------------------------------------------------------
    # Skills Normalisation
    # -------------------------------------------------------------------------
    def clean_skills_array(self, skills_str: str) -> List[str]:
        """
        Split a skills string into a normalised array.

        Handles comma, pipe, semicolon, and slash separators.
        Removes duplicates and empty entries.

        Returns:
            List of lowercase stripped skill strings.
        """
        if not skills_str:
            return []

        # Split on common delimiters
        raw_skills = re.split(r"[,|;/]", skills_str)
        cleaned = []
        seen = set()
        for skill in raw_skills:
            s = skill.strip().lower()
            # Remove numeric-only, very short, or known noise
            if s and len(s) > 1 and s not in seen and not s.isdigit():
                seen.add(s)
                cleaned.append(s)

        return cleaned[:20]  # Cap at 20 skills

    # -------------------------------------------------------------------------
    # Data Validation
    # -------------------------------------------------------------------------
    def validate_job_data(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate a job dictionary before insertion.

        Returns:
            {"valid": bool, "errors": List[str]}
        """
        errors = []

        if not job.get("title") or len(str(job["title"]).strip()) < 2:
            errors.append("title is required and must be at least 2 characters")

        if not job.get("company") or len(str(job["company"]).strip()) < 1:
            errors.append("company is required")

        if job.get("job_url") and len(str(job["job_url"])) > 1000:
            errors.append("job_url exceeds 1000 characters")

        if job.get("source") and job["source"] not in ("naukri", "linkedin", "indeed"):
            errors.append(f"source must be naukri, linkedin, or indeed, got: {job['source']}")

        return {"valid": len(errors) == 0, "errors": errors}

    # -------------------------------------------------------------------------
    # Full Pipeline
    # -------------------------------------------------------------------------
    def process_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the full cleaning pipeline on a raw job dict.

        Normalises location, salary, experience, skills, and validates.
        Adds is_valid flag.
        """
        # Normalise location
        if job.get("location"):
            job["location_normalized"] = self.normalize_location(job["location"])

        # Normalise salary (if not already done by scraper)
        if job.get("salary") and not job.get("salary_min"):
            job.update(self.normalize_salary(job["salary"]))

        # Normalise experience (if not already done by scraper)
        if job.get("experience") and not job.get("experience_min_years"):
            job.update(self.normalize_experience(job["experience"]))

        # Clean skills
        if job.get("skills") and isinstance(job["skills"], str):
            job["skills"] = self.clean_skills_array(job["skills"])

        # Extract walk-in details from description if missing
        if job.get("job_description") and not job.get("walkin_dates"):
            walkin_info = self.parse_walkin_dates(job["job_description"])
            for k, v in walkin_info.items():
                if v and not job.get(k):
                    job[k] = v

        # Validate
        validation = self.validate_job_data(job)
        job["_valid"] = validation["valid"]
        job["_errors"] = validation["errors"]

        return job
