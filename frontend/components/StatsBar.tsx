"use client";
// components/StatsBar.tsx — Live stats ticker

import type { StatsResponse } from "@/lib/api";

interface Props {
  stats: StatsResponse | null;
}

export default function StatsBar({ stats }: Props) {
  if (!stats) return null;

  const items = [
    { label: "Total Jobs", value: stats.total_jobs?.toLocaleString(), icon: "📋" },
    { label: "Walk-in", value: stats.total_walkin_jobs?.toLocaleString(), icon: "🚶" },
    { label: "Fresher Friendly", value: stats.total_fresher_jobs?.toLocaleString(), icon: "🌱" },
    { label: "This Week", value: stats.jobs_this_week?.toLocaleString(), icon: "📅" },
  ];

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
      gap: "1rem",
      marginBottom: "2rem",
    }}>
      {items.map(item => (
        <div key={item.label} style={{
          background: "var(--bg-card)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-sm)",
          padding: "1rem 1.25rem",
          textAlign: "center",
        }}>
          <div style={{ fontSize: "1.5rem", marginBottom: "0.25rem" }}>{item.icon}</div>
          <div style={{
            fontSize: "1.6rem",
            fontWeight: 800,
            background: "linear-gradient(135deg, #a78bfa, #f59e0b)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}>
            {item.value || "—"}
          </div>
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>
            {item.label}
          </div>
        </div>
      ))}
    </div>
  );
}
