"""
services/apify_service.py — Job aggregation via Apify's Google Jobs Scraper.
Replaces legacy scrapers with a robust, cloud-based solution.
"""

import os
import logging
from typing import List, Dict, Any
from apify_client import ApifyClient

logger = logging.getLogger(__name__)

def fetch_jobs_from_apify() -> List[Dict[str, Any]]:
    """
    Fetches job data using Apify's 'apify/google-jobs-scraper'.
    Filters results for Naukri sources or Walk-in titles.
    """
    api_token = os.getenv("APIFY_API_TOKEN")
    if not api_token:
        logger.error("APIFY_API_TOKEN is not set in environment variables")
        return []

    client = ApifyClient(api_token)
    
    # Exact queries requested
    queries = [
        "walk in jobs Hyderabad",
        "walk in jobs Bangalore",
        "walk in jobs Chennai"
    ]
    
    all_jobs = []
    
    try:
        logger.info("Starting Apify Google Jobs Scraper...")
        
        # Prepare actor input
        run_input = {
            "queries": "\n".join(queries),
            "maxItems": 30,
            "maxPagesPerQuery": 2,
            "proxyConfiguration": {"useApifyProxy": True}
        }

        # Run the actor
        # Actor name: apify/google-jobs-scraper
        run = client.actor("apify/google-jobs-scraper").call(run_input=run_input)
        
        logger.info("Apify run completed. Fetching results from dataset: %s", run["defaultDatasetId"])
        
        raw_count = 0
        # Iterate through the results
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            raw_count += 1
            
            via = item.get("via", "").lower()
            title = item.get("title", "").lower()
            
            # Apply filters: Naukri source OR Walk-in in title
            if "naukri" in via or "walk" in title:
                job_data = {
                    "title": item.get("title"),
                    "company": item.get("companyName"),
                    "location": item.get("location"),
                    "job_url": item.get("jobUrl") or item.get("url"),
                    "source": "Google Jobs (via Apify)",
                    "via": item.get("via"),
                    "is_walkin": "walk" in title,
                    "is_fresher_friendly": "fresher" in title or "0-" in title
                }
                all_jobs.append(job_data)

        logger.info("Apify Summary: Raw jobs: %d | Filtered jobs: %d", raw_count, len(all_jobs))

    except Exception as e:
        logger.error("Error during Apify fetch: %s", e, exc_info=True)
        return []

    return all_jobs
