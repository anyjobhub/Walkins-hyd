"use client";
// app/jobs/[id]/page.tsx — Job detail page

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Header from "@/components/Header";
import { getJob, type Job } from "@/lib/api";

const SOURCE_COLORS: Record<string, string> = {
  naukri: "#ff6b35",
  linkedin: "#0a66c2",
  indeed: "#003a9b",
};

export default function JobDetailPage() {
  const params = useParams();
  const id = Number(params?.id);
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getJob(id)
      .then(setJob)
      .catch(() => setError("Job not found or server unavailable."))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <>
        <Header />
        <main className="container" style={{ padding: "3rem 1.5rem" }}>
          <div style={{ maxWidth: 700, margin: "0 auto" }}>
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="skeleton" style={{ height: 40, marginBottom: "1rem", borderRadius: 8 }} />
            ))}
          </div>
        </main>
      </>
    );
  }

  if (error || !job) {
    return (
      <>
        <Header />
        <main className="container" style={{ padding: "3rem 1.5rem", textAlign: "center" }}>
          <div style={{ fontSize: "4rem", marginBottom: "1rem" }}>😕</div>
          <h2>{error || "Job not found"}</h2>
          <Link href="/" style={{ color: "var(--accent-glow)", textDecoration: "none" }}>
            ← Back to all jobs
          </Link>
        </main>
      </>
    );
  }

  const sourceColor = SOURCE_COLORS[job.source || ""] || "var(--accent-primary)";

  return (
    <>
      <Header />
      <main style={{ padding: "2.5rem 0 4rem" }}>
        <div className="container" style={{ maxWidth: 780 }}>
          {/* Back button */}
          <Link
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              color: "var(--text-secondary)",
              textDecoration: "none",
              fontSize: "0.88rem",
              marginBottom: "1.5rem",
              transition: "color 0.2s",
            }}
            onMouseEnter={e => (e.currentTarget.style.color = "var(--text-primary)")}
            onMouseLeave={e => (e.currentTarget.style.color = "var(--text-secondary)")}
          >
            ← Back to listings
          </Link>

          {/* Job card */}
          <div style={{
            background: "var(--gradient-card)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            padding: "2rem",
            position: "relative",
            overflow: "hidden",
          }}>
            {/* Glow */}
            <div style={{
              position: "absolute",
              top: -60,
              right: -60,
              width: 200,
              height: 200,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${sourceColor}20, transparent 70%)`,
              pointerEvents: "none",
            }} />

            {/* Badges */}
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1.25rem" }}>
              {job.is_walkin && (
                <span style={badgeStyle("#f59e0b")}>🚶 WALK-IN INTERVIEW</span>
              )}
              {job.is_fresher_friendly && (
                <span style={badgeStyle("#10b981")}>🌱 FRESHER FRIENDLY</span>
              )}
              {job.source && (
                <span style={badgeStyle(sourceColor)}>{job.source.toUpperCase()}</span>
              )}
            </div>

            {/* Title & Company */}
            <h1 style={{
              fontSize: "clamp(1.4rem, 3vw, 2rem)",
              fontWeight: 800,
              margin: "0 0 0.5rem",
              color: "var(--text-primary)",
              lineHeight: 1.25,
            }}>{job.title}</h1>
            <p style={{ margin: "0 0 1.5rem", fontSize: "1.05rem", color: "var(--text-secondary)" }}>
              🏢 {job.company}
            </p>

            {/* Info grid */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
              gap: "1rem",
              background: "var(--bg-surface)",
              borderRadius: 12,
              padding: "1.25rem",
              marginBottom: "1.5rem",
              border: "1px solid var(--border)",
            }}>
              <InfoItem icon="📍" label="Location" value={job.location_normalized || job.location || "—"} />
              <InfoItem icon="💰" label="Salary" value={job.salary_label || job.salary || "Not Disclosed"} />
              <InfoItem icon="📊" label="Experience" value={job.experience || "Any"} />
              <InfoItem icon="🎯" label="Level" value={job.experience_level ? capitalize(job.experience_level) : "—"} />
              {job.posted_date_human && (
                <InfoItem icon="🕐" label="Posted" value={job.posted_date_human} />
              )}
              {job.extracted_at_human && (
                <InfoItem icon="🔄" label="Scraped" value={job.extracted_at_human} />
              )}
            </div>

            {/* Walk-in details */}
            {job.is_walkin && (job.walkin_dates || job.walkin_time || job.address) && (
              <div style={{
                background: "rgba(245, 158, 11, 0.08)",
                border: "1px solid rgba(245, 158, 11, 0.25)",
                borderRadius: 12,
                padding: "1.25rem",
                marginBottom: "1.5rem",
              }}>
                <h3 style={{ margin: "0 0 0.75rem", color: "#f59e0b", fontSize: "0.95rem", fontWeight: 700 }}>
                  🗓 WALK-IN DETAILS
                </h3>
                {job.walkin_dates && <InfoItem icon="📅" label="Date(s)" value={job.walkin_dates} />}
                {job.walkin_time && <InfoItem icon="⏰" label="Time" value={job.walkin_time} />}
                {job.address && <InfoItem icon="📍" label="Venue" value={job.address} />}
                {job.contact_person && <InfoItem icon="👤" label="Contact Person" value={job.contact_person} />}
                {job.contact_phone && <InfoItem icon="📱" label="Phone" value={job.contact_phone} />}
                {job.contact_email && <InfoItem icon="📧" label="Email" value={job.contact_email} />}
              </div>
            )}

            {/* Skills */}
            {job.skills && job.skills.length > 0 && (
              <div style={{ marginBottom: "1.5rem" }}>
                <h3 style={{ margin: "0 0 0.75rem", fontSize: "0.9rem", color: "var(--text-secondary)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  🛠 Required Skills
                </h3>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                  {job.skills.map((skill, i) => (
                    <span key={i} style={{
                      padding: "4px 14px",
                      borderRadius: 20,
                      fontSize: "0.8rem",
                      background: "rgba(124, 58, 237, 0.12)",
                      color: "var(--accent-glow)",
                      border: "1px solid rgba(124, 58, 237, 0.25)",
                    }}>
                      {skill}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Description */}
            {job.job_description && (
              <div style={{ marginBottom: "2rem" }}>
                <h3 style={{ margin: "0 0 0.75rem", fontSize: "0.9rem", color: "var(--text-secondary)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  📄 Job Description
                </h3>
                <div style={{
                  color: "var(--text-secondary)",
                  fontSize: "0.9rem",
                  lineHeight: 1.7,
                  whiteSpace: "pre-wrap",
                  background: "var(--bg-surface)",
                  padding: "1rem",
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  maxHeight: "400px",
                  overflowY: "auto",
                }}>
                  {job.job_description}
                </div>
              </div>
            )}

            {/* CTA buttons */}
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
              {job.job_url && (
                <a
                  href={job.job_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  id="apply-btn"
                  style={{
                    flex: 1,
                    minWidth: 160,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                    padding: "14px 24px",
                    borderRadius: 12,
                    background: "linear-gradient(135deg, var(--accent-primary), #a855f7)",
                    color: "#fff",
                    textDecoration: "none",
                    fontWeight: 700,
                    fontSize: "1rem",
                    transition: "transform 0.2s, box-shadow 0.2s",
                    animation: "pulse-glow 3s ease-in-out infinite",
                  }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLAnchorElement).style.transform = "translateY(-2px)";
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLAnchorElement).style.transform = "";
                  }}
                >
                  Apply Now →
                </a>
              )}
              <a
                href={`https://t.me/share/url?url=${encodeURIComponent(job.job_url || "")}&text=${encodeURIComponent(`🔥 ${job.title} at ${job.company}`)}`}
                target="_blank"
                rel="noopener noreferrer"
                id="share-telegram-btn"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "14px 24px",
                  borderRadius: 12,
                  background: "rgba(33, 150, 243, 0.15)",
                  color: "#2196f3",
                  textDecoration: "none",
                  fontWeight: 600,
                  fontSize: "0.95rem",
                  border: "1px solid rgba(33, 150, 243, 0.3)",
                  transition: "background 0.2s",
                }}
              >
                📱 Share on Telegram
              </a>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

function InfoItem({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginBottom: "2px", textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {icon} {label}
      </div>
      <div style={{ fontSize: "0.9rem", color: "var(--text-primary)", fontWeight: 600 }}>
        {value}
      </div>
    </div>
  );
}

function badgeStyle(color: string): React.CSSProperties {
  return {
    padding: "4px 14px",
    borderRadius: 20,
    fontSize: "0.75rem",
    fontWeight: 700,
    color: color,
    background: `${color}18`,
    border: `1px solid ${color}44`,
    letterSpacing: "0.04em",
  };
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
