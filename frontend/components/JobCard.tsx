"use client";
// components/JobCard.tsx

import Link from "next/link";
import type { Job } from "@/lib/api";

interface JobCardProps {
  job: Job;
  index?: number;
}

const SOURCE_COLORS: Record<string, string> = {
  naukri: "#ff6b35",
  linkedin: "#0a66c2",
  indeed: "#003a9b",
};

export default function JobCard({ job, index = 0 }: JobCardProps) {
  const sourceColor = SOURCE_COLORS[job.source || ""] || "var(--accent-primary)";
  const delay = `${index * 0.05}s`;

  return (
    <Link href={`/jobs/${job.id}`} style={{ textDecoration: "none" }}>
      <article
        className="fade-up"
        style={{
          animationDelay: delay,
          background: "var(--gradient-card)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "1.5rem",
          cursor: "pointer",
          transition: "transform 0.25s, box-shadow 0.25s, border-color 0.25s",
          boxShadow: "var(--shadow-card)",
          position: "relative",
          overflow: "hidden",
        }}
        onMouseEnter={e => {
          const el = e.currentTarget;
          el.style.transform = "translateY(-4px)";
          el.style.boxShadow = "var(--shadow-card-hover)";
          el.style.borderColor = "var(--border-bright)";
        }}
        onMouseLeave={e => {
          const el = e.currentTarget;
          el.style.transform = "";
          el.style.boxShadow = "var(--shadow-card)";
          el.style.borderColor = "var(--border)";
        }}
      >
        {/* Accent glow top-right */}
        <div style={{
          position: "absolute",
          top: -40,
          right: -40,
          width: 120,
          height: 120,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${sourceColor}22, transparent 70%)`,
          pointerEvents: "none",
        }} />

        {/* Header row */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{
              margin: 0,
              fontSize: "1.05rem",
              fontWeight: 700,
              color: "var(--text-primary)",
              lineHeight: 1.3,
              marginBottom: "0.3rem",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}>
              {job.title}
            </h3>
            <p style={{
              margin: 0,
              fontSize: "0.9rem",
              color: "var(--text-secondary)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}>
              🏢 {job.company}
            </p>
          </div>

          {/* Source badge */}
          {job.source && (
            <span style={{
              marginLeft: "0.75rem",
              padding: "3px 10px",
              borderRadius: 20,
              fontSize: "0.7rem",
              fontWeight: 700,
              color: sourceColor,
              background: `${sourceColor}18`,
              border: `1px solid ${sourceColor}33`,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              flexShrink: 0,
            }}>
              {job.source}
            </span>
          )}
        </div>

        {/* Info row */}
        <div style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          marginBottom: "0.875rem",
          fontSize: "0.82rem",
          color: "var(--text-secondary)",
        }}>
          {job.location && (
            <span>📍 {job.location_normalized || job.location}</span>
          )}
          {job.salary && (
            <span>💰 {job.salary_label || job.salary}</span>
          )}
          {job.experience && (
            <span>📊 {job.experience}</span>
          )}
          {job.extracted_at_human && (
            <span>🕐 {job.extracted_at_human}</span>
          )}
        </div>

        {/* Skills */}
        {job.skills && job.skills.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.35rem", marginBottom: "0.875rem" }}>
            {job.skills.slice(0, 5).map((skill, i) => (
              <span key={i} style={{
                padding: "2px 10px",
                borderRadius: 20,
                fontSize: "0.72rem",
                background: "rgba(124, 58, 237, 0.12)",
                color: "var(--accent-glow)",
                border: "1px solid rgba(124, 58, 237, 0.2)",
              }}>
                {skill}
              </span>
            ))}
            {job.skills.length > 5 && (
              <span style={{
                padding: "2px 8px",
                borderRadius: 20,
                fontSize: "0.72rem",
                color: "var(--text-muted)",
              }}>
                +{job.skills.length - 5} more
              </span>
            )}
          </div>
        )}

        {/* Badges */}
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {job.is_walkin && (
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "4px",
              padding: "4px 12px",
              borderRadius: 20,
              fontSize: "0.75rem",
              fontWeight: 700,
              background: "linear-gradient(135deg, #f59e0b22, #f59e0b11)",
              color: "#f59e0b",
              border: "1px solid #f59e0b44",
              animation: "pulse-glow 2s ease-in-out infinite",
            }}>
              🚶 WALK-IN
            </span>
          )}
          {job.is_fresher_friendly && (
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "4px",
              padding: "4px 12px",
              borderRadius: 20,
              fontSize: "0.75rem",
              fontWeight: 700,
              background: "rgba(16, 185, 129, 0.12)",
              color: "#10b981",
              border: "1px solid rgba(16, 185, 129, 0.3)",
            }}>
              🌱 FRESHER OK
            </span>
          )}
          {job.walkin_dates && (
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "4px",
              padding: "4px 12px",
              borderRadius: 20,
              fontSize: "0.75rem",
              color: "var(--text-secondary)",
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
            }}>
              📅 {job.walkin_dates}
            </span>
          )}
        </div>
      </article>
    </Link>
  );
}
