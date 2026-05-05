"use client";
// app/page.tsx — Home page with job listings

import { useState, useEffect, useCallback } from "react";
import Header from "@/components/Header";
import FilterBar from "@/components/FilterBar";
import JobCard from "@/components/JobCard";
import StatsBar from "@/components/StatsBar";
import { getJobs, getStats, type Job, type JobFilters, type StatsResponse } from "@/lib/api";

export default function HomePage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [filters, setFilters] = useState<JobFilters>({ page: 1, limit: 20 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalPages, setTotalPages] = useState(1);
  const [totalJobs, setTotalJobs] = useState(0);

  const fetchJobs = useCallback(async (f: JobFilters) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getJobs(f);
      setJobs(data.jobs);
      setTotalPages(data.pages);
      setTotalJobs(data.total);
    } catch (e) {
      setError("Failed to load jobs. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs(filters);
  }, [filters, fetchJobs]);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
  }, []);

  return (
    <>
      <Header />
      <main style={{ minHeight: "100vh" }}>

        {/* Hero */}
        <section style={{
          background: "var(--gradient-hero)",
          padding: "4rem 0 3rem",
          textAlign: "center",
          position: "relative",
          overflow: "hidden",
        }}>
          {/* Background orbs */}
          <div style={{
            position: "absolute", inset: 0, pointerEvents: "none",
            background: "radial-gradient(ellipse at 20% 50%, rgba(124,58,237,0.12) 0%, transparent 60%), radial-gradient(ellipse at 80% 20%, rgba(245,158,11,0.08) 0%, transparent 60%)",
          }} />

          <div className="container" style={{ position: "relative" }}>
            <div style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "6px 16px",
              borderRadius: 20,
              background: "rgba(124, 58, 237, 0.15)",
              border: "1px solid rgba(124, 58, 237, 0.3)",
              color: "#a78bfa",
              fontSize: "0.82rem",
              fontWeight: 600,
              marginBottom: "1.5rem",
              letterSpacing: "0.05em",
            }}>
              🔄 Updated every 4 hours
            </div>

            <h1 style={{
              fontSize: "clamp(2rem, 5vw, 3.5rem)",
              fontWeight: 900,
              margin: "0 0 1rem",
              lineHeight: 1.15,
              background: "linear-gradient(135deg, #f1f1f6 30%, #a78bfa 70%, #f59e0b 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}>
              Find Walk-in Jobs<br />Across India Today
            </h1>
            <p style={{
              fontSize: "1.1rem",
              color: "var(--text-secondary)",
              maxWidth: "550px",
              margin: "0 auto 2rem",
            }}>
              Curated walk-in interview opportunities from Naukri, LinkedIn &amp; Indeed.
              No registration. No spam. Just jobs.
            </p>
          </div>
        </section>

        {/* Main content */}
        <section style={{ padding: "2.5rem 0 4rem" }}>
          <div className="container">
            <StatsBar stats={stats} />
            <FilterBar filters={filters} onFilterChange={setFilters} />

            {/* Results header */}
            <div style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "1.25rem",
            }}>
              <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem", margin: 0 }}>
                {loading ? "Loading jobs..." : `${totalJobs.toLocaleString()} jobs found`}
              </p>
            </div>

            {/* Error state */}
            {error && (
              <div style={{
                padding: "2rem",
                textAlign: "center",
                background: "rgba(239, 68, 68, 0.1)",
                border: "1px solid rgba(239, 68, 68, 0.3)",
                borderRadius: "var(--radius)",
                color: "#ef4444",
                marginBottom: "1.5rem",
              }}>
                ⚠️ {error}
              </div>
            )}

            {/* Loading skeletons */}
            {loading && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "1rem" }}>
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="skeleton" style={{ height: 220, borderRadius: "var(--radius)" }} />
                ))}
              </div>
            )}

            {/* Job grid */}
            {!loading && jobs.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "1rem" }}>
                {jobs.map((job, i) => (
                  <JobCard key={job.id} job={job} index={i} />
                ))}
              </div>
            )}

            {/* Empty state */}
            {!loading && jobs.length === 0 && !error && (
              <div style={{
                padding: "4rem 2rem",
                textAlign: "center",
                color: "var(--text-secondary)",
              }}>
                <div style={{ fontSize: "4rem", marginBottom: "1rem" }}>📭</div>
                <h3 style={{ color: "var(--text-primary)", marginBottom: "0.5rem" }}>No jobs found</h3>
                <p>Try adjusting your filters or check back soon.</p>
              </div>
            )}

            {/* Pagination */}
            {!loading && totalPages > 1 && (
              <div style={{
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
                gap: "0.5rem",
                marginTop: "2.5rem",
              }}>
                <PageButton
                  label="← Prev"
                  disabled={(filters.page || 1) <= 1}
                  onClick={() => setFilters(f => ({ ...f, page: (f.page || 1) - 1 }))}
                />
                <span style={{ color: "var(--text-secondary)", fontSize: "0.9rem", padding: "0 0.5rem" }}>
                  Page {filters.page || 1} of {totalPages}
                </span>
                <PageButton
                  label="Next →"
                  disabled={(filters.page || 1) >= totalPages}
                  onClick={() => setFilters(f => ({ ...f, page: (f.page || 1) + 1 }))}
                />
              </div>
            )}
          </div>
        </section>
      </main>

      <footer style={{
        background: "var(--bg-surface)",
        borderTop: "1px solid var(--border)",
        padding: "2rem 0",
        textAlign: "center",
        color: "var(--text-muted)",
        fontSize: "0.85rem",
      }}>
        <div className="container">
          <p>© 2024 WalkIn Jobs India — Powered by data from Naukri, LinkedIn & Indeed</p>
          <p style={{ marginTop: "0.5rem" }}>
            Scraping responsibly with 3-second delays • Respects robots.txt
          </p>
        </div>
      </footer>
    </>
  );
}

function PageButton({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "8px 20px",
        borderRadius: 8,
        border: "1px solid var(--border)",
        background: disabled ? "transparent" : "var(--accent-primary)",
        color: disabled ? "var(--text-muted)" : "#fff",
        fontSize: "0.88rem",
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
        transition: "all 0.2s",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {label}
    </button>
  );
}
