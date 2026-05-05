"""
tasks/scraper_tasks.py — Background tasks for running the Apify job scraper.
Integrated with the database and deduplication services.
"""

import logging
from flask import Flask
from services.apify_service import fetch_jobs_from_apify
from services.deduplication import DeduplicationService
from models.job import db, Job
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def run_scraper_pipeline(app: Flask):
    """
    Main background task to fetch jobs from Apify,
    deduplicate them, and save to database.
    """
    with app.app_context():
        logger.info("🚀 Starting Apify Scraper Pipeline...")
        
        try:
            # 1. Fetch from Apify
            apify_jobs = fetch_jobs_from_apify()
            
            if not apify_jobs:
                logger.warning("No jobs fetched from Apify. Pipeline finished.")
                return

            # 2. Initialise Deduplication
            dedup_service = DeduplicationService()
            new_jobs_count = 0
            
            # 3. Process and Save
            for job_data in apify_jobs:
                # Check if job already exists by URL
                existing = Job.query.filter_by(job_url=job_data["job_url"]).first()
                if existing:
                    continue

                # Deduplicate based on content similarity
                is_duplicate, _ = dedup_service.is_duplicate(job_data, Job.query.all())
                if is_duplicate:
                    continue

                # Create new job record
                new_job = Job(
                    title=job_data["title"],
                    company=job_data["company"],
                    location=job_data["location"],
                    job_url=job_data["job_url"],
                    source=job_data["source"],
                    is_walkin=job_data["is_walkin"],
                    is_fresher_friendly=job_data["is_fresher_friendly"],
                    extracted_at=datetime.now(timezone.utc)
                )
                
                db.session.add(new_job)
                new_jobs_count += 1

            db.session.commit()
            logger.info("✅ Pipeline Complete: %d new jobs saved to database.", new_jobs_count)
            
        except Exception as e:
            logger.error("Pipeline Error: %s", e, exc_info=True)
            db.session.rollback()
