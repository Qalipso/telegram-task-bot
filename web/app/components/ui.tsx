/* Small presentational helpers shared across pages: badges, confidence bar,
   status constants, and formatting. Pure components — no hooks. */
import type { Priority, WorkItemStatus, CandidateType, CandidateStatus } from "../lib/types";

/* ---- Icon primitive -------------------------------------------------- */
const PATHS: Record<string, React.ReactNode> = {
  logo: <><circle cx="9" cy="9" r="8" stroke="currentColor" strokeWidth="1.5"/><circle cx="9" cy="9" r="3.5" fill="currentColor"/></>,
  close: <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>,
  refresh: <><path d="M13.5 2.5A7 7 0 1 0 15 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><path d="M13.5 2.5V6.5H9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></>,
  plus: <path d="M8 2v12M2 8h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>,
  check: <path d="M2 8l4 4 8-8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>,
  search: <><circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5"/><path d="M13 13l-3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></>,
  arrow: <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>,
  chevron: <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>,
  user: <><circle cx="8" cy="5.5" r="3" stroke="currentColor" strokeWidth="1.5"/><path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></>,
  power: <><path d="M8 2v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><path d="M5 4.3A6 6 0 1 0 11 4.3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></>,
};

export function Icon({
  name,
  size = 16,
  className,
  "aria-label": label,
  "aria-hidden": hidden,
}: {
  name: keyof typeof PATHS;
  size?: number;
  className?: string;
  "aria-label"?: string;
  "aria-hidden"?: boolean | "true" | "false";
}) {
  return (
    <svg
      width={size} height={size}
      viewBox="0 0 16 16" fill="none"
      className={className}
      aria-label={label}
      aria-hidden={hidden ?? (label ? undefined : true)}
    >
      {PATHS[name]}
    </svg>
  );
}

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

export const PRIORITY_LABEL: Record<string, string> = {
  critical: "Critical", high: "High", medium: "Mid", low: "Low",
};

export function PriorityBadge({ priority }: { priority: Priority | null }) {
  if (!priority) return <span className="badge">No priority</span>;
  return <span className={`badge prio-${priority}`}>{PRIORITY_LABEL[priority] ?? priority}</span>;
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
