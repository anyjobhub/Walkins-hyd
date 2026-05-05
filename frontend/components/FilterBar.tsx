"use client";
// components/FilterBar.tsx

import { useState, useCallback } from "react";
import type { JobFilters } from "@/lib/api";
import { CITIES, EXPERIENCE_LEVELS } from "@/lib/api";

interface FilterBarProps {
  filters: JobFilters;
  onFilterChange: (filters: JobFilters) => void;
}

export default function FilterBar({ filters, onFilterChange }: FilterBarProps) {
  const [searchInput, setSearchInput] = useState(filters.search || "");

  const update = (patch: Partial<JobFilters>) => {
    onFilterChange({ ...filters, ...patch, page: 1 });
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    update({ search: searchInput });
  };

  const clearAll = () => {
    setSearchInput("");
    onFilterChange({ page: 1, limit: 20 });
  };

  const hasActiveFilters = Boolean(
    filters.search || filters.location || filters.walkin_only ||
    filters.fresher_friendly || filters.experience_level || filters.source
  );

  return (
    <div style={{
      background: "var(--bg-card)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius)",
      padding: "1.25rem 1.5rem",
      marginBottom: "1.5rem",
    }}>
      {/* Search bar */}
      <form onSubmit={handleSearchSubmit} style={{ marginBottom: "1rem" }}>
        <div style={{ position: "relative" }}>
          <span style={{
            position: "absolute",
            left: "1rem",
            top: "50%",
            transform: "translateY(-50%)",
            fontSize: "1rem",
            pointerEvents: "none",
          }}>🔍</span>
          <input
            id="job-search"
            type="text"
            placeholder="Search by job title, company, or skill..."
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            style={{
              width: "100%",
              padding: "0.75rem 1rem 0.75rem 2.75rem",
              borderRadius: 10,
              border: "1px solid var(--border)",
              background: "var(--bg-surface)",
              color: "var(--text-primary)",
              fontSize: "0.95rem",
              outline: "none",
              transition: "border-color 0.2s",
            }}
            onFocus={e => e.target.style.borderColor = "var(--accent-primary)"}
            onBlur={e => e.target.style.borderColor = "var(--border)"}
          />
          <button
            type="submit"
            style={{
              position: "absolute",
              right: "0.5rem",
              top: "50%",
              transform: "translateY(-50%)",
              padding: "6px 16px",
              borderRadius: 8,
              border: "none",
              background: "var(--accent-primary)",
              color: "#fff",
              fontSize: "0.85rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Search
          </button>
        </div>
      </form>

      {/* Filter row */}
      <div style={{
        display: "flex",
        flexWrap: "wrap",
        gap: "0.75rem",
        alignItems: "center",
      }}>
        {/* City selector */}
        <select
          id="filter-location"
          value={filters.location || ""}
          onChange={e => update({ location: e.target.value || undefined })}
          style={selectStyle}
        >
          <option value="">📍 All Cities</option>
          {CITIES.slice(1).map(city => (
            <option key={city} value={city}>{city}</option>
          ))}
        </select>

        {/* Experience level */}
        <select
          id="filter-experience"
          value={filters.experience_level || ""}
          onChange={e => update({ experience_level: e.target.value || undefined })}
          style={selectStyle}
        >
          {EXPERIENCE_LEVELS.map(lvl => (
            <option key={lvl.value} value={lvl.value}>{lvl.label}</option>
          ))}
        </select>

        {/* Source selector */}
        <select
          id="filter-source"
          value={filters.source || ""}
          onChange={e => update({ source: e.target.value || undefined })}
          style={selectStyle}
        >
          <option value="">📡 All Sources</option>
          <option value="naukri">Naukri</option>
          <option value="linkedin">LinkedIn</option>
          <option value="indeed">Indeed</option>
        </select>

        {/* Toggles */}
        <ToggleButton
          id="filter-walkin"
          active={!!filters.walkin_only}
          label="🚶 Walk-in Only"
          color="#f59e0b"
          onClick={() => update({ walkin_only: !filters.walkin_only })}
        />

        <ToggleButton
          id="filter-fresher"
          active={!!filters.fresher_friendly}
          label="🌱 Freshers"
          color="#10b981"
          onClick={() => update({ fresher_friendly: !filters.fresher_friendly })}
        />

        {/* Clear all */}
        {hasActiveFilters && (
          <button
            id="filter-clear"
            onClick={clearAll}
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: "1px solid var(--border)",
              background: "transparent",
              color: "var(--text-secondary)",
              fontSize: "0.82rem",
              cursor: "pointer",
              transition: "color 0.2s, border-color 0.2s",
            }}
            onMouseEnter={e => {
              (e.currentTarget).style.color = "var(--accent-red)";
              (e.currentTarget).style.borderColor = "var(--accent-red)";
            }}
            onMouseLeave={e => {
              (e.currentTarget).style.color = "var(--text-secondary)";
              (e.currentTarget).style.borderColor = "var(--border)";
            }}
          >
            ✕ Clear All
          </button>
        )}
      </div>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--bg-surface)",
  color: "var(--text-primary)",
  fontSize: "0.85rem",
  cursor: "pointer",
  outline: "none",
};

interface ToggleProps {
  id: string;
  active: boolean;
  label: string;
  color: string;
  onClick: () => void;
}

function ToggleButton({ id, active, label, color, onClick }: ToggleProps) {
  return (
    <button
      id={id}
      onClick={onClick}
      style={{
        padding: "8px 14px",
        borderRadius: 8,
        border: `1px solid ${active ? color : "var(--border)"}`,
        background: active ? `${color}18` : "transparent",
        color: active ? color : "var(--text-secondary)",
        fontSize: "0.85rem",
        fontWeight: active ? 600 : 400,
        cursor: "pointer",
        transition: "all 0.2s",
      }}
    >
      {label}
    </button>
  );
}
