// lib/api.ts — API client for the Flask backend

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000";

export interface Job {
  id: number;
  title: string;
  company: string;
  location: string;
  location_normalized?: string;
  salary?: string;
  salary_min?: number;
  salary_max?: number;
  salary_currency?: string;
  salary_label?: string;
  experience?: string;
  experience_min_years?: number;
  experience_max_years?: number;
  experience_level?: string;
  skills?: string[];
  walkin_dates?: string;
  walkin_time?: string;
  address?: string;
  contact_person?: string;
  contact_phone?: string;
  contact_email?: string;
  job_url?: string;
  job_description?: string;
  source?: string;
  is_walkin: boolean;
  is_fresher_friendly: boolean;
  extracted_at?: string;
  extracted_at_human?: string;
  posted_date?: string;
  posted_date_human?: string;
  telegram_posted?: boolean;
}

export interface JobsResponse {
  jobs: Job[];
  total: number;
  page: number;
  pages: number;
  limit: number;
}

export interface StatsResponse {
  total_jobs: number;
  total_walkin_jobs: number;
  total_fresher_jobs: number;
  jobs_this_week: number;
  jobs_this_month: number;
  unposted_jobs: number;
  sources: Record<string, number>;
  last_scrape_time?: string;
}

export interface JobFilters {
  location?: string;
  company?: string;
  walkin_only?: boolean;
  fresher_friendly?: boolean;
  salary_min?: number;
  salary_max?: number;
  experience_level?: string;
  source?: string;
  search?: string;
  page?: number;
  limit?: number;
}

async function apiFetch<T>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.set(k, String(v));
      }
    });
  }

  const res = await fetch(url.toString(), {
    next: { revalidate: 60 },  // ISR: revalidate every 60s
  });

  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

export async function getJobs(filters: JobFilters = {}): Promise<JobsResponse> {
  const params: Record<string, string | number | boolean> = {
    page: filters.page || 1,
    limit: filters.limit || 20,
  };
  if (filters.location) params.location = filters.location;
  if (filters.company) params.company = filters.company;
  if (filters.walkin_only) params.walkin_only = "true";
  if (filters.fresher_friendly) params.fresher_friendly = "true";
  if (filters.salary_min) params.salary_min = filters.salary_min;
  if (filters.salary_max) params.salary_max = filters.salary_max;
  if (filters.experience_level) params.experience_level = filters.experience_level;
  if (filters.source) params.source = filters.source;

  if (filters.search) {
    return apiFetch<JobsResponse>("/api/jobs/search", { q: filters.search, page: params.page, limit: params.limit });
  }

  return apiFetch<JobsResponse>("/api/jobs", params);
}

export async function startScrape(key: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/api/scrape/start", { key });
}

export async function getScrapeStatus(key: string): Promise<{ status: string; service: string }> {
  return apiFetch<{ status: string; service: string }>("/api/scrape/status", { key });
}

export async function getJob(id: number): Promise<Job> {
  return apiFetch<Job>(`/api/jobs/${id}`);
}

export async function getStats(): Promise<StatsResponse> {
  return apiFetch<StatsResponse>("/api/stats");
}

export const CITIES = [
  "All India", "Delhi", "NCR", "Mumbai", "Bengaluru", "Hyderabad",
  "Chennai", "Pune", "Kolkata", "Ahmedabad", "Noida", "Gurugram",
  "Navi Mumbai", "Thane", "Coimbatore", "Chandigarh", "Jaipur",
  "Lucknow", "Indore", "Bhopal",
];

export const EXPERIENCE_LEVELS = [
  { value: "", label: "Any Experience" },
  { value: "fresher", label: "Fresher (0-1 yr)" },
  { value: "junior", label: "Junior (1-3 yrs)" },
  { value: "mid", label: "Mid (3-7 yrs)" },
  { value: "senior", label: "Senior (7+ yrs)" },
];
