"""
models/__init__.py — Expose all models from one import path.
"""
from .job import db, Job, ScrapLog, TelegramUser, JobDuplicate

__all__ = ["db", "Job", "ScrapLog", "TelegramUser", "JobDuplicate"]
