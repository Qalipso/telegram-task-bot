/* Small presentational helpers shared across pages: badges, confidence bar,
   status constants, and formatting. Pure components — no hooks. */
import type { Priority, WorkItemStatus, CandidateType, CandidateStatus } from "../lib/types";

export const WORK_STATUSES: WorkItemStatus[] = [
  "inbox", "backlog", "ready", "in_progress", "blocked", "review", "done", "cancelled", "archived",
];

export const STATUS_LABEL: Record<string, string> = {
  inbox: "Inbox", backlog: "Backlog", ready: "Ready", in_progress: "In Progress",
  blocked: "Blocked", review: "Review", done: "Done", cancelled: "Cancelled", archived: "Archived",
  new: "New", needs_review: "Needs Review", edited: "Edited", approved: "Approved",
  rejected: "Rejected", duplicate: "Duplicate", error: "Error",
};

export const COLUMN_ACCENT: Record<WorkItemStatus, string> = {
  inbox: "#8a96a3", backlog: "#7c8aa0", ready: "#2a5bd7", in_progress: "#2a8bd7",
  blocked: "#c4810b", review: "#7a52c4", done: "#1f9d57", cancelled: "#b0b8c0", archived: "#9aa3ad",
};

export function PriorityBadge({ priority }: { priority: Priority | null }) {
  if (!priority) return <span className="badge">no priority</span>;
  return <span className={`badge prio-${priority}`}>{priority}</span>;
}

export function TypeBadge({ type }: { type: CandidateType }) {
  return <span className="badge type">{type}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge st st-${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function ConfidenceBar({ value }: { value: number | null }) {
  if (value == null) return <span className="faint">—</span>;
  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? "var(--success)" : value >= 0.6 ? "var(--warn)" : "var(--danger)";
  return (
    <span className="conf" title={`Task confidence ${pct}%`}>
      <span className="track"><span className="fill" style={{ width: `${pct}%`, background: color }} /></span>
      <span className="pct" style={{ color }}>{pct}%</span>
    </span>
  );
}

export function MissingFields({ fields }: { fields: string[] | null | undefined }) {
  if (!fields || fields.length === 0) return null;
  return (
    <span className="chips">
      {fields.map((f) => <span key={f} className="chip">missing: {f.replace(/_/g, " ")}</span>)}
    </span>
  );
}

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const CANDIDATE_STATUSES: CandidateStatus[] = [
  "new", "needs_review", "edited", "approved", "rejected", "duplicate", "error",
];
