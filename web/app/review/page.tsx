"use client";
import { useCallback, useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { apiGet, apiPatch, apiPost, ApiError } from "../lib/api";
import { useToast } from "../components/Toast";
import {
  PriorityBadge, TypeBadge, StatusBadge, ConfidenceBar, MissingFields,
  fmtDate, fmtDateTime, CANDIDATE_STATUSES, STATUS_LABEL, PRIORITY_LABEL,
} from "../components/ui";
import type { Assignee, Candidate, CandidateDetail, CandidateType, Priority } from "../lib/types";

const TYPES: CandidateType[] = ["task", "request", "reminder", "idea", "knowledge"];
const PRIORITIES: Priority[] = ["high", "medium", "low"];

export default function ReviewPage() {
  return <AppShell><Review /></AppShell>;
}

function Review() {
  const [items, setItems] = useState<Candidate[]>([]);
  const [filter, setFilter] = useState<string>("pending");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CandidateDetail | null>(null);
  const [assignees, setAssignees] = useState<Assignee[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (filter === "pending") {
        const all = await apiGet<Candidate[]>("/api/candidates");
        setItems(all.filter((c) => c.status === "new" || c.status === "needs_review" || c.status === "edited"));
      } else {
        const q = filter ? `?status=${filter}` : "";
        setItems(await apiGet<Candidate[]>(`/api/candidates${q}`));
      }
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403
        ? "Candidate review requires an admin account."
        : "Failed to load candidates.");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { apiGet<Assignee[]>("/api/assignees").then(setAssignees).catch(() => {}); }, []);

  async function open(id: number) {
    setSelected(await apiGet<CandidateDetail>(`/api/candidates/${id}`));
  }

  return (
    <div className="container">
      <div className="page-head">
        <h1>Review Queue</h1>
        <span className="sub">AI-extracted candidates awaiting human approval. Approving promotes a candidate to a Work Item.</span>
      </div>

      <div className="toolbar">
        <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <span>Status</span>
          <select className="select" style={{ width: 180 }} value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="pending">To review</option>
            <option value="">All</option>
            {CANDIDATE_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        </label>
        <button className="btn sm right" onClick={load}>↻ Refresh</button>
      </div>

      {error && <div className="banner error" style={{ marginBottom: 14 }}>{error}</div>}

      <div className="card">
        {loading ? (
          <div className="loading-wrap"><span className="spinner" /> Loading candidates…</div>
        ) : items.length === 0 ? (
          <div className="empty">
            <div className="big">📭</div>
            <div><b>{filter === "pending"
              ? "Nothing to review — every candidate has been triaged."
              : `No candidates${filter ? ` with status “${STATUS_LABEL[filter]}”` : ""}.`}</b></div>
            <div className="muted">Run a sync and let extraction produce candidates, then triage them here.</div>
          </div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: "38%" }}>Candidate</th>
                <th>Type</th><th>Priority</th><th>Status</th><th>Confidence</th><th>Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => open(c.id)}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{c.title || <span className="faint">untitled</span>}</div>
                    <div style={{ marginTop: 4 }}><MissingFields fields={c.missing_fields} /></div>
                  </td>
                  <td><TypeBadge type={c.candidate_type} /></td>
                  <td><PriorityBadge priority={c.priority} /></td>
                  <td><StatusBadge status={c.status} /></td>
                  <td><ConfidenceBar value={c.task_confidence} /></td>
                  <td className="muted">{fmtDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && (
        <CandidateDrawer
          detail={selected}
          assignees={assignees}
          onClose={() => setSelected(null)}
          onChanged={() => { setSelected(null); load(); }}
        />
      )}
    </div>
  );
}

function CandidateDrawer({ detail, assignees, onClose, onChanged }: {
  detail: CandidateDetail; assignees: Assignee[]; onClose: () => void; onChanged: () => void;
}) {
  const c = detail.candidate;
  const locked = c.status === "approved" || c.status === "rejected";
  const [title, setTitle] = useState(c.title ?? "");
  const [summary, setSummary] = useState(c.summary ?? "");
  const [type, setType] = useState<CandidateType>(c.candidate_type);
  const [priority, setPriority] = useState<string>(c.priority ?? "");
  const [due, setDue] = useState<string>(c.due_date ? c.due_date.slice(0, 10) : "");
  const [assigneeId, setAssigneeId] = useState<string>(
    (detail.assignees.find((a) => a.is_primary) ?? detail.assignees[0])?.assignee_id?.toString() ?? "",
  );
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  async function run(fn: () => Promise<void>, label: string) {
    setBusy(true);
    try { await fn(); }
    catch (e) {
      toast({
        kind: "error",
        message: e instanceof ApiError ? e.message : `${label} failed.`,
        action: { label: "Retry", onClick: () => run(fn, label) },
      });
    }
    finally { setBusy(false); }
  }

  const save = () => run(async () => {
    await apiPatch(`/api/candidates/${c.id}`, {
      title, summary, candidate_type: type,
      priority: priority || null,
      due_date: due ? `${due}T00:00:00Z` : null,
      assignee_ids: assigneeId ? [Number(assigneeId)] : [],
    });
    toast({ kind: "success", message: "Candidate saved." });
    onChanged();
  }, "Save");

  const approve = () => run(async () => {
    const wi = await apiPost<{ id: number }>(`/api/candidates/${c.id}/approve`);
    toast({ kind: "success", message: `Approved → Work Item #${wi.id} created.` });
    onChanged();
  }, "Approve");

  const reject = () => run(async () => {
    await apiPost(`/api/candidates/${c.id}/reject`);
    toast({ kind: "info", message: "Candidate rejected." });
    onChanged();
  }, "Reject");

  return (
    <div className="overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="dh">
          <StatusBadge status={c.status} />
          <h2 style={{ flex: 1 }}>Candidate #{c.id}</h2>
          <button className="btn ghost sm" onClick={onClose}>✕</button>
        </div>
        <div className="db">
          {locked && <div className="banner ok" style={{ background: "var(--surface-2)", color: "var(--text-muted)", borderColor: "var(--border)" }}>
            This candidate is {c.status} and can no longer be edited.
          </div>}

          <label className="field">Title
            <input className="input" value={title} disabled={locked} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="field">Summary
            <textarea className="textarea" value={summary} disabled={locked} onChange={(e) => setSummary(e.target.value)} />
          </label>
          <div className="row" style={{ gap: 12 }}>
            <label className="field" style={{ flex: 1 }}>Type
              <select className="select" value={type} disabled={locked} onChange={(e) => setType(e.target.value as CandidateType)}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="field" style={{ flex: 1 }}>Priority
              <select className="select" value={priority} disabled={locked} onChange={(e) => setPriority(e.target.value)}>
                <option value="">none</option>
                {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}
              </select>
            </label>
            <label className="field" style={{ flex: 1 }}>Due date
              <input className="input" type="date" value={due} disabled={locked} onChange={(e) => setDue(e.target.value)} />
            </label>
          </div>

          <label className="field">Assignee <span className="faint" style={{ fontWeight: 400 }}>(responsible person)</span>
            <select className="select" value={assigneeId} disabled={locked} onChange={(e) => setAssigneeId(e.target.value)}>
              <option value="">— unassigned —</option>
              {assignees.filter((a) => a.is_active || String(a.id) === assigneeId).map((a) => (
                <option key={a.id} value={a.id}>{a.display_name || (a.telegram_username ? "@" + a.telegram_username : `#${a.id}`)}</option>
              ))}
            </select>
          </label>

          <MissingFields fields={c.missing_fields} />

          <div>
            <div className="kv">
              <span className="k">Confidence</span><ConfidenceBar value={c.task_confidence} />
              <span className="k">Created</span><span className="muted">{fmtDateTime(c.created_at)}</span>
            </div>
          </div>

          <div>
            <div className="k" style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>
              Source messages ({detail.messages.length})
            </div>
            <div className="col" style={{ gap: 6 }}>
              {detail.messages.map((m) => (
                <div key={m.message_id} className="msg-line">
                  <div className="row" style={{ gap: 6, marginBottom: 4 }}>
                    <b>{m.sender || "unknown"}</b>
                    <span className={`badge st st-${m.role}`}>{m.role}</span>
                    <span className="faint right">{fmtDateTime(m.sent_at)}</span>
                  </div>
                  <div>{m.text ? m.text : <span className="faint">(no text content)</span>}</div>
                </div>
              ))}
            </div>
          </div>

          {!locked && (
            <div className="row" style={{ gap: 8, paddingTop: 4 }}>
              <button className="btn" onClick={save} disabled={busy}>Save edits</button>
              <button className="btn success" onClick={approve} disabled={busy}>✓ Approve → Work Item</button>
              <button className="btn danger-outline right" onClick={reject} disabled={busy}>Reject</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
