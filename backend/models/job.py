"""
models/job.py — SQLAlchemy ORM models for the Walk-in Jobs Aggregation System.

Models:
  - Job            : Core job posting record
  - ScrapLog       : Audit log for each scraping run
  - TelegramUser   : Subscribed Telegram users and preferences
  - JobDuplicate   : Tracks duplicate relationships between jobs
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    Boolean, Column, DateTime, Numeric, Integer,
    String, Text, BigInteger, ForeignKey, ARRAY, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

db = SQLAlchemy()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# Job Model
# =============================================================================
class Job(db.Model):
    """
    Represents a single job posting scraped from Naukri, LinkedIn, or Indeed.

    The job_hash field (SHA-256 of company+title+location) is the primary
    deduplication key. is_duplicate flags jobs detected as near-duplicates.
    """

    __tablename__ = "jobs"

    # --- Primary Key ---
    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- Core Fields ---
    title = Column(String(255), nullable=False, index=True)
    company = Column(String(255), nullable=False, index=True)
    location = Column(String(255))
    location_normalized = Column(String(100), index=True)

    # --- Compensation ---
    salary = Column(String(100))
    salary_min = Column(Integer)          # Annual, in INR
    salary_max = Column(Integer)
    salary_currency = Column(String(10), default="INR")

    # --- Experience ---
    experience = Column(String(100))
    experience_min_years = Column(Numeric(4, 1))
    experience_max_years = Column(Numeric(4, 1))
    experience_level = Column(String(20))  # fresher/junior/mid/senior

    # --- Skills ---
    skills = Column(ARRAY(Text))          # PostgreSQL native array

    # --- Walk-in Specifics ---
    walkin_dates = Column(String(255))
    walkin_time = Column(String(100))
    address = Column(Text)
    contact_person = Column(String(255))
    contact_phone = Column(String(20))
    contact_email = Column(String(255))

    # --- Source ---
    job_url = Column(String(1000))
    job_description = Column(Text)
    source = Column(String(50), index=True)     # naukri/linkedin/indeed
    source_id = Column(String(500))
    job_hash = Column(String(64), index=True)   # SHA-256 for dedup

    # --- Flags ---
    is_walkin = Column(Boolean, default=False, index=True)
    is_fresher_friendly = Column(Boolean, default=False, index=True)
    is_duplicate = Column(Boolean, default=False, index=True)
    duplicate_of_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)

    # --- Timestamps ---
    extracted_at = Column(DateTime(timezone=True), default=_utcnow, index=True)
    posted_date = Column(DateTime(timezone=True))
    last_checked = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # --- Telegram ---
    telegram_posted = Column(Boolean, default=False, index=True)
    telegram_posted_at = Column(DateTime(timezone=True))

    # --- Relationships ---
    duplicates = relationship(
        "JobDuplicate",
        foreign_keys="JobDuplicate.original_job_id",
        back_populates="original_job",
        cascade="all, delete-orphan",
    )

    # -------------------------------------------------------------------------
    # Unique constraint on (source_id, source)
    # -------------------------------------------------------------------------
    __table_args__ = (
        db.UniqueConstraint("source_id", "source", name="uq_source_id_source"),
    )

    # -------------------------------------------------------------------------
    # Class Methods
    # -------------------------------------------------------------------------
    @classmethod
    def compute_hash(cls, company: str, title: str, location: str = "") -> str:
        """
        Generate a SHA-256 hash for deduplication.

        Normalises inputs (lowercase, strip) before hashing so that
        minor formatting differences don't create false positives.
        """
        raw = f"{company.lower().strip()}|{title.lower().strip()}|{(location or '').lower().strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create a Job instance from a scraper result dictionary."""
        job = cls()
        for key, value in data.items():
            if hasattr(job, key):
                setattr(job, key, value)
        # Auto-compute hash if not provided
        if not job.job_hash and job.company and job.title:
            job.job_hash = cls.compute_hash(
                job.company, job.title, job.location or ""
            )
        return job

    # -------------------------------------------------------------------------
    # Instance Methods
    # -------------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Convert Job to a JSON-serialisable dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "location_normalized": self.location_normalized,
            "salary": self.salary,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "experience": self.experience,
            "experience_min_years": float(self.experience_min_years) if self.experience_min_years else None,
            "experience_max_years": float(self.experience_max_years) if self.experience_max_years else None,
            "experience_level": self.experience_level,
            "skills": self.skills or [],
            "walkin_dates": self.walkin_dates,
            "walkin_time": self.walkin_time,
            "address": self.address,
            "contact_person": self.contact_person,
            "contact_phone": self.contact_phone,
            "contact_email": self.contact_email,
            "job_url": self.job_url,
            "job_description": self.job_description,
            "source": self.source,
            "source_id": self.source_id,
            "is_walkin": self.is_walkin,
            "is_fresher_friendly": self.is_fresher_friendly,
            "is_duplicate": self.is_duplicate,
            "extracted_at": self.extracted_at.isoformat() if self.extracted_at else None,
            "posted_date": self.posted_date.isoformat() if self.posted_date else None,
            "telegram_posted": self.telegram_posted,
        }

    def to_telegram_format(self) -> str:
        """
        Format job as a Telegram message string.

        Uses Telegram's HTML parse mode for rich formatting.
        Returns a string <= 4096 characters (Telegram's limit).
        """
        walkin_badge = "🚶 <b>WALK-IN</b> | " if self.is_walkin else ""
        fresher_badge = "🌱 <b>FRESHER FRIENDLY</b>" if self.is_fresher_friendly else ""
        badges = walkin_badge + fresher_badge

        salary_str = self.salary or "Not Disclosed"
        exp_str = self.experience or "Any"
        location_str = self.location or "India"

        walkin_section = ""
        if self.is_walkin:
            walkin_section = (
                f"\n\n🗓 <b>WALK-IN DETAILS</b>\n"
                f"📅 Dates: {self.walkin_dates or 'See description'}\n"
                f"⏰ Time: {self.walkin_time or 'See description'}\n"
                f"📍 Venue: {self.address or 'See job link'}"
            )

        contact_section = ""
        if self.contact_person or self.contact_phone:
            contact_section = (
                f"\n\n📞 <b>Contact</b>\n"
                f"{'👤 ' + self.contact_person + chr(10) if self.contact_person else ''}"
                f"{'📱 ' + self.contact_phone if self.contact_phone else ''}"
            )

        skills_str = ""
        if self.skills:
            skills_str = "\n🛠 <b>Skills:</b> " + ", ".join(self.skills[:8])  # Max 8 skills

        msg = (
            f"{badges}\n\n"
            f"🔥 <b>{self.title}</b>\n"
            f"🏢 {self.company}\n"
            f"📍 {location_str}\n"
            f"\n"
            f"💰 <b>Salary:</b> {salary_str}\n"
            f"📊 <b>Experience:</b> {exp_str}"
            f"{skills_str}"
            f"{walkin_section}"
            f"{contact_section}\n"
            f"\n"
            f"🔗 <a href='{self.job_url}'>View Full Job</a>\n"
            f"\n"
            f"📋 Source: {(self.source or '').capitalize()} | "
            f"🕐 {self.extracted_at.strftime('%d %b %Y') if self.extracted_at else 'Today'}"
        )

        # Ensure within Telegram limit
        if len(msg) > 4000:
            msg = msg[:3997] + "..."

        return msg

    def to_website_format(self) -> Dict[str, Any]:
        """Format for the website display (adds computed fields)."""
        data = self.to_dict()
        # Add human-readable date
        if self.extracted_at:
            data["extracted_at_human"] = self.extracted_at.strftime("%d %b %Y")
        if self.posted_date:
            data["posted_date_human"] = self.posted_date.strftime("%d %b %Y")
        # Add salary range label
        if self.salary_min and self.salary_max:
            lpa_min = round(self.salary_min / 100000, 1)
            lpa_max = round(self.salary_max / 100000, 1)
            data["salary_label"] = f"₹{lpa_min}–{lpa_max} LPA"
        return data

    def is_fresh_enough(self, days: int = 30) -> bool:
        """Return True if the job was posted within the last N days."""
        if not self.extracted_at:
            return False
        delta = _utcnow() - self.extracted_at.replace(tzinfo=timezone.utc)
        return delta.days <= days

    def __repr__(self) -> str:
        return f"<Job id={self.id} title='{self.title}' company='{self.company}'>"


# =============================================================================
# ScrapLog Model
# =============================================================================
class ScrapLog(db.Model):
    """Audit log entry for each scraping run."""

    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # success / failed / partial
    jobs_found = Column(Integer, default=0)
    jobs_added = Column(Integer, default=0)
    jobs_skipped = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True))
    duration_secs = Column(Numeric(8, 2))
    error_message = Column(Text)
    metadata_ = Column("metadata", JSON, default=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "status": self.status,
            "jobs_found": self.jobs_found,
            "jobs_added": self.jobs_added,
            "jobs_skipped": self.jobs_skipped,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_secs": float(self.duration_secs) if self.duration_secs else None,
            "error_message": self.error_message,
        }

    def __repr__(self) -> str:
        return f"<ScrapLog id={self.id} source='{self.source}' status='{self.status}'>"


# =============================================================================
# TelegramUser Model
# =============================================================================
class TelegramUser(db.Model):
    """A user who has interacted with the Telegram bot."""

    __tablename__ = "telegram_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255))
    first_name = Column(String(255))
    last_name = Column(String(255))
    preferences = Column(JSON, default=dict)   # {locations:[], salary_min, fresher_only}
    subscribed = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    last_active = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "preferences": self.preferences or {},
            "subscribed": self.subscribed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def display_name(self) -> str:
        """Best available name for the user."""
        if self.first_name:
            return f"{self.first_name} {self.last_name or ''}".strip()
        return self.username or f"User #{self.user_id}"

    def __repr__(self) -> str:
        return f"<TelegramUser id={self.id} user_id={self.user_id}>"


# =============================================================================
# JobDuplicate Model
# =============================================================================
class JobDuplicate(db.Model):
    """
    Tracks which jobs were detected as duplicates of which originals.
    Allows forensic analysis of deduplication quality.
    """

    __tablename__ = "job_duplicates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_job_id = Column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    duplicate_job_id = Column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    similarity_score = Column(Numeric(5, 2))   # 0–100
    detected_at = Column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    original_job = relationship(
        "Job",
        foreign_keys=[original_job_id],
        back_populates="duplicates",
    )
    duplicate_job = relationship("Job", foreign_keys=[duplicate_job_id])

    __table_args__ = (
        db.UniqueConstraint(
            "original_job_id", "duplicate_job_id", name="uq_duplicate_pair"
        ),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "original_job_id": self.original_job_id,
            "duplicate_job_id": self.duplicate_job_id,
            "similarity_score": float(self.similarity_score) if self.similarity_score else None,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<JobDuplicate orig={self.original_job_id} "
            f"dup={self.duplicate_job_id} score={self.similarity_score}>"
        )
