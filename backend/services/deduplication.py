"""
services/deduplication.py — Deduplication engine for job records.

Uses:
  1. SHA-256 hash (exact match on company+title+location)
  2. Fuzzy string matching (thefuzz) for near-duplicates
  3. DB lookup before insert

The goal: ensure no duplicate jobs appear in the database or on Telegram.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from thefuzz import fuzz

from config import Config

logger = logging.getLogger(__name__)


class DeduplicationService:
    """
    Deduplication service for job records.

    Two jobs are considered duplicates if:
      1. Their job_hash is identical (same company+title+location, normalised), OR
      2. The fuzzy similarity of (company + title) exceeds the configured threshold.
    """

    def __init__(self, threshold: int = None):
        self.threshold = threshold or Config.dedup.SIMILARITY_THRESHOLD
        logger.info(
            "DeduplicationService initialised with similarity threshold: %d%%",
            self.threshold,
        )

    # -------------------------------------------------------------------------
    # Hashing
    # -------------------------------------------------------------------------
    def generate_job_hash(self, job: Dict[str, Any]) -> str:
        """
        Generate a SHA-256 hash based on company + title + location.

        Normalises inputs (lowercase, strip, remove special chars) so that
        minor formatting differences don't produce different hashes.
        """
        company = _normalise(job.get("company", ""))
        title = _normalise(job.get("title", ""))
        location = _normalise(job.get("location", "") or job.get("location_normalized", ""))
        raw = f"{company}|{title}|{location}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # -------------------------------------------------------------------------
    # Fuzzy comparison
    # -------------------------------------------------------------------------
    def compute_similarity(self, job1: Dict[str, Any], job2: Dict[str, Any]) -> float:
        """
        Compute a similarity score (0-100) between two jobs.

        Uses a weighted combination of:
          - Title similarity (weight 0.5)
          - Company similarity (weight 0.35)
          - Location similarity (weight 0.15)
        """
        title_score = fuzz.token_sort_ratio(
            _normalise(job1.get("title", "")),
            _normalise(job2.get("title", "")),
        )
        company_score = fuzz.token_sort_ratio(
            _normalise(job1.get("company", "")),
            _normalise(job2.get("company", "")),
        )
        location_score = fuzz.token_sort_ratio(
            _normalise(job1.get("location", "") or ""),
            _normalise(job2.get("location", "") or ""),
        )

        weighted = (
            0.50 * title_score +
            0.35 * company_score +
            0.15 * location_score
        )
        return round(weighted, 2)

    def is_duplicate(
        self, new_job: Dict[str, Any], existing_job: Dict[str, Any]
    ) -> Tuple[bool, float]:
        """
        Determine if new_job is a duplicate of existing_job.

        Returns:
            (is_duplicate: bool, similarity_score: float)
        """
        # Fast path: hash match
        if (
            new_job.get("job_hash") and
            new_job["job_hash"] == existing_job.get("job_hash")
        ):
            return True, 100.0

        # Slow path: fuzzy match
        score = self.compute_similarity(new_job, existing_job)
        return score >= self.threshold, score

    # -------------------------------------------------------------------------
    # Batch deduplication (in-memory, before DB insert)
    # -------------------------------------------------------------------------
    def deduplicate_batch(
        self, jobs: List[Dict[str, Any]]
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Deduplicate a list of jobs before they're inserted into the DB.

        Compares each job against all previously accepted jobs in the batch.

        Returns:
            (unique_jobs, duplicate_jobs)
        """
        unique: List[Dict] = []
        duplicates: List[Dict] = []

        for job in jobs:
            # Ensure hash is computed
            if not job.get("job_hash"):
                job["job_hash"] = self.generate_job_hash(job)

            dup_found = False
            for accepted in unique:
                is_dup, score = self.is_duplicate(job, accepted)
                if is_dup:
                    logger.debug(
                        "Duplicate detected: '%s' @ '%s' (score=%.1f%%)",
                        job.get("title"),
                        job.get("company"),
                        score,
                    )
                    job["is_duplicate"] = True
                    job["_duplicate_of"] = accepted
                    job["_similarity_score"] = score
                    duplicates.append(job)
                    dup_found = True
                    break

            if not dup_found:
                unique.append(job)

        logger.info(
            "Batch dedup: %d unique, %d duplicates (from %d total)",
            len(unique), len(duplicates), len(jobs),
        )
        return unique, duplicates

    # -------------------------------------------------------------------------
    # DB-aware deduplication
    # -------------------------------------------------------------------------
    def find_duplicate_in_db(
        self, new_job: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Check if new_job already exists in the database.

        First checks by job_hash (fast), then by fuzzy match on recent records.

        Returns:
            Existing job dict if duplicate found, else None.
        """
        from models.job import Job

        # Fast path: exact hash match
        if new_job.get("job_hash"):
            existing = Job.query.filter_by(job_hash=new_job["job_hash"]).first()
            if existing:
                logger.debug(
                    "DB hash match for '%s' @ '%s'",
                    new_job.get("title"), new_job.get("company"),
                )
                return existing.to_dict()

        # Fuzzy match: query recent jobs from same source or similar title
        title = new_job.get("title", "")
        company = new_job.get("company", "")

        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        candidates = (
            Job.query
            .filter(
                Job.extracted_at >= cutoff,
                Job.is_duplicate == False,
            )
            .with_entities(
                Job.id, Job.title, Job.company,
                Job.location, Job.job_hash, Job.source_id,
            )
            .limit(500)
            .all()
        )

        for candidate in candidates:
            candidate_dict = {
                "id": candidate.id,
                "title": candidate.title,
                "company": candidate.company,
                "location": candidate.location,
                "job_hash": candidate.job_hash,
            }
            is_dup, score = self.is_duplicate(new_job, candidate_dict)
            if is_dup:
                logger.info(
                    "DB fuzzy match: '%s' @ '%s' ≈ existing id=%d (score=%.1f%%)",
                    title, company, candidate.id, score,
                )
                return {**candidate_dict, "_similarity_score": score}

        return None

    # -------------------------------------------------------------------------
    # Merge helpers
    # -------------------------------------------------------------------------
    def merge_duplicate_jobs(
        self, primary: Dict[str, Any], duplicate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge two duplicate jobs, keeping the most complete data.

        primary:    The job to keep (already in DB or first in batch)
        duplicate:  The new/duplicate job

        Strategy: prefer non-None values from duplicate if primary is missing them.
        """
        merged = dict(primary)  # start from primary

        fields_to_merge = [
            "salary", "salary_min", "salary_max",
            "walkin_dates", "walkin_time", "address",
            "contact_person", "contact_phone", "contact_email",
            "job_description", "skills", "experience",
            "posted_date",
        ]

        for field in fields_to_merge:
            if not primary.get(field) and duplicate.get(field):
                merged[field] = duplicate[field]

        # Combine job_urls from both sources
        urls = set()
        for j in (primary, duplicate):
            if j.get("job_url"):
                urls.add(j["job_url"])
        if len(urls) > 1:
            merged["_all_urls"] = list(urls)

        return merged


# =============================================================================
# Helpers
# =============================================================================
def _normalise(text: str) -> str:
    """Lowercase, strip, and remove special chars for comparison."""
    import re
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)   # Remove punctuation
    text = re.sub(r"\s+", " ", text)        # Collapse whitespace
    return text.strip()
