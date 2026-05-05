"""
services/apify_service.py — Job aggregation for Indian walk-in jobs using johnvc~Google-Jobs-Scraper.
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

    # Build the structured message as per requirement
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
    Fetches Indian walk-in jobs for Hyderabad, Bangalore, and Chennai.
    Uses multi-city logic to call the actor separately for each city.
    """
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        logger.error("APIFY_API_TOKEN is not set")
        return []

    client = ApifyClient(api_token)
    cities = ["Hyderabad", "Bangalore", "Chennai"]
    relevant_jobs = []
    
    for city in cities:
        try:
            logger.info("Triggering Apify Scraper for city: %s", city)
            
            run_input = {
                "query": f"walk in jobs {city}",
                "location": f"{city}, India",
                "include_lrad": False,
                "lrad_value": "5",
                "maxItems": 10  # Keeping max items low for free plan
            }

            # Using johnvc~Google-Jobs-Scraper as requested
            run = client.actor("johnvc~Google-Jobs-Scraper").call(run_input=run_input)
            
            city_raw_count = 0
            for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                city_raw_count += 1
                
                title = str(item.get("title") or "").lower()
                
                # Filter Rules: "walk" OR "bpo" OR "customer" in title
                if "walk" in title or "bpo" in title or "customer" in title:
                    job_data = {
                        "title": item.get("title"),
                        "company": item.get("companyName") or item.get("company"),
                        "location": item.get("location") or city.upper(),
                        "job_url": item.get("jobUrl") or item.get("url"),
                        "source": f"Google Jobs ({city})",
                        "experience": item.get("experience") or "Not Mentioned",
                        "is_walkin": "walk" in title,
                        "is_fresher_friendly": any(k in title for k in ["fresher", "0-", "entry"])
                    }
                    relevant_jobs.append(job_data)

            logger.info("City: %s | Total: %d | Relevant: %d", city, city_raw_count, len(relevant_jobs))

        except Exception as e:
            logger.error("Error fetching jobs for %s: %s", city, e)
            continue

    return relevant_jobs

def get_formatted_messages() -> List[str]:
    """
    High-level flow: Fetch, Filter, and Format.
    Returns a list of ready-to-post message strings.
    """
    jobs = fetch_jobs_from_apify()
    return [format_job_message(j) for j in jobs]