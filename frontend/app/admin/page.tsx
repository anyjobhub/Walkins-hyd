"use client";

import { useState, useEffect, useRef } from "react";
import Header from "@/components/Header";
import JobCard from "@/components/JobCard";
import { startScrape, getJobs, type Job } from "@/lib/api";

const ADMIN_KEY = "7f05fe47abfe473393eecc4aa3290347";

export default function AdminPage() {
  const [isScraping, setIsScraping] = useState(false);
  const [liveJobs, setLiveJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState<string>("Ready to Scrape");
  const [error, setError] = useState<string | null>(null);
  const pollInterval = useRef<NodeJS.Timeout | null>(null);

  const handleStartScrape = async () => {
    try {
      setError(null);
      setIsScraping(true);
      setStatus("Scraper started... Fetching live jobs from Apify.");
      
      const response = await startScrape(ADMIN_KEY);
      if (response.status) {
        // Start polling for new jobs
        startPolling();
      }
    } catch (e) {
      setError("Failed to start scraper. Check connection or key.");
      setIsScraping(false);
    }
  };

  const handleStopScrape = () => {
    stopPolling();
    setIsScraping(false);
    setStatus("Stopped monitoring live updates.");
  };

  const startPolling = () => {
    if (pollInterval.current) return;
    
    // Poll every 5 seconds
    pollInterval.current = setInterval(async () => {
      try {
        const data = await getJobs({ limit: 10, page: 1 });
        setLiveJobs(data.jobs);
      } catch (e) {
        console.error("Polling error:", e);
      }
    }, 5000);
  };

  const stopPolling = () => {
    if (pollInterval.current) {
      clearInterval(pollInterval.current);
      pollInterval.current = null;
    }
  };

  useEffect(() => {
    return () => stopPolling();
  }, []);

  return (
    <>
      <Header />
      <main style={{ minHeight: "100vh", padding: "2rem 0" }}>
        <div className="container">
          
          {/* Admin Header */}
          <div style={{
            background: "var(--bg-surface)",
            padding: "2rem",
            borderRadius: "var(--radius)",
            border: "1px solid var(--border)",
            marginBottom: "2rem",
            display: "flex",
            flexDirection: "column",
            gap: "1.5rem"
          }}>
            <div>
              <h1 style={{ fontSize: "1.75rem", fontWeight: 800, marginBottom: "0.5rem" }}>
                Scraper Control Center
              </h1>
              <p style={{ color: "var(--text-secondary)", margin: 0 }}>
                Trigger the Apify Google Jobs Scraper manually and monitor results in real-time.
              </p>
            </div>

            <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
              {!isScraping ? (
                <button
                  onClick={handleStartScrape}
                  style={{
                    padding: "12px 24px",
                    borderRadius: 12,
                    background: "var(--accent-primary)",
                    color: "#fff",
                    fontWeight: 700,
                    border: "none",
                    cursor: "pointer",
                    fontSize: "1rem",
                    transition: "all 0.2s"
                  }}
                >
                  🚀 Start Scrape
                </button>
              ) : (
                <button
                  onClick={handleStopScrape}
                  style={{
                    padding: "12px 24px",
                    borderRadius: 12,
                    background: "#ef4444",
                    color: "#fff",
                    fontWeight: 700,
                    border: "none",
                    cursor: "pointer",
                    fontSize: "1rem",
                    transition: "all 0.2s"
                  }}
                >
                  🛑 Stop Monitoring
                </button>
              )}

              <div style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "8px 16px",
                borderRadius: 20,
                background: isScraping ? "rgba(34, 197, 94, 0.1)" : "rgba(107, 114, 128, 0.1)",
                border: `1px solid ${isScraping ? "rgba(34, 197, 94, 0.3)" : "rgba(107, 114, 128, 0.3)"}`,
                color: isScraping ? "#22c55e" : "#9ca3af",
                fontSize: "0.85rem",
                fontWeight: 600
              }}>
                <span style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: isScraping ? "#22c55e" : "#9ca3af",
                  display: "block"
                }} />
                {status}
              </div>
            </div>

            {error && (
              <div style={{ color: "#ef4444", fontSize: "0.9rem", fontWeight: 500 }}>
                ⚠️ {error}
              </div>
            )}
          </div>

          {/* Live Feed Section */}
          <div>
            <h2 style={{ fontSize: "1.25rem", fontWeight: 700, marginBottom: "1.25rem", display: "flex", alignItems: "center", gap: "10px" }}>
              Live Job Feed {isScraping && <span className="pulse" style={{ fontSize: "0.75rem", color: "#22c55e", fontWeight: 600 }}>(UPDATING LIVE)</span>}
            </h2>

            {liveJobs.length > 0 ? (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "1rem" }}>
                {liveJobs.map((job, i) => (
                  <JobCard key={job.id} job={job} index={i} />
                ))}
              </div>
            ) : (
              <div style={{
                padding: "4rem",
                textAlign: "center",
                background: "var(--bg-surface)",
                borderRadius: "var(--radius)",
                border: "2px dashed var(--border)",
                color: "var(--text-muted)"
              }}>
                <div style={{ fontSize: "2.5rem", marginBottom: "1rem" }}>📡</div>
                <p>No jobs found in the last few minutes. Start the scraper to see live cards.</p>
              </div>
            )}
          </div>
        </div>
      </main>

      <style jsx global>{`
        .pulse {
          animation: pulse-animation 2s infinite;
        }
        @keyframes pulse-animation {
          0% { opacity: 1; }
          50% { opacity: 0.4; }
          100% { opacity: 1; }
        }
      `}</style>
    </>
  );
}
