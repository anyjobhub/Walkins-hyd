"""
services/apify_service.py — Job aggregation and WhatsApp message formatting.
"""

import os
import logging
from typing import List, Dict, Any
from apify_client import ApifyClient

logger = logging.getLogger(__name__)

def format_job_message(job: Dict[str, Any]) -> str:
    """
    Converts a job dictionary into a strictly formatted WhatsApp/Telegram message.
    Used for ready-to-post channel updates.
    """
    # Uppercase company and location, use fallbacks for missing data
    company = str(job.get("company") or "Not Mentioned").strip().upper()
    title = str(job.get("title") or "Not Mentioned").strip()
    location = str(job.get("location") or "Not Mentioned").strip().upper()
    experience = str(job.get("experience") or "Not Mentioned").strip()
    job_url = str(job.get("job_url") or "Not Mentioned").strip()

    # Build the structured message
    message = (
        f"{company} is hiring for {title} | {location}\n\n"
        f"Experience: {experience}\n\n"
        f"WALK-IN DETAILS:\n"
        f"Not Mentioned\n\n"
        f"🚨 JOB LINK:\n"
        f"{job_url}\n\n"
        f"📌Follow Walk-ins Everyday for job opportunities:\n"
        f"https://whatsapp.com/channel/0029Vb7RR53G3R3j5is87T0j"
    )
    return message

def fetch_jobs_from_apify() -> List[Dict[str, Any]]:
    """
    Fetches raw job data from Apify and filters it.
    Returns a list of job dictionaries compatible with the database.
    """
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        logger.error("APIFY_API_TOKEN is not set")
        return []

    client = ApifyClient(api_token)
    
    queries = [
        "walk in jobs Hyderabad",
        "walk in jobs Bangalore",
        "walk in jobs Chennai"
    ]
    
    relevant_jobs = []
    
    try:
        logger.info("Triggering Apify Google Jobs Scraper...")
        
        run_input = {
            "queries": "\n".join(queries),
            "maxItems": 30,
            "maxPagesPerQuery": 2,
            "proxyConfiguration": {"useApifyProxy": True}
        }

        run = client.actor("apify~google-jobs-scraper").call(run_input=run_input)
        
        raw_count = 0
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            raw_count += 1
            
            via = str(item.get("via") or "").lower()
            title = str(item.get("title") or "").lower()
            
            # Filter Rules: "walk" in title OR "naukri" in via
            if "walk" in title or "naukri" in via:
                job_data = {
                    "title": item.get("title"),
                    "company": item.get("companyName"),
                    "location": item.get("location"),
                    "job_url": item.get("jobUrl") or item.get("url"),
                    "source": f"Google Jobs via {item.get('via', 'Apify')}",
                    "experience": item.get("experience"),
                    "is_walkin": "walk" in title,
                    "is_fresher_friendly": "fresher" in title or "0-" in title
                }
                relevant_jobs.append(job_data)

        logger.info("Apify Done: Total: %d | Relevant: %d", raw_count, len(relevant_jobs))

    except Exception as e:
        logger.error("Apify Service Error: %s", e, exc_info=True)
        return []

    return relevant_jobs

def get_formatted_messages() -> List[str]:
    """
    High-level flow: Fetch, Filter, and Format.
    Returns a list of ready-to-post message strings.
    """
    jobs = fetch_jobs_from_apify()
    return [format_job_message(j) for j in jobs]