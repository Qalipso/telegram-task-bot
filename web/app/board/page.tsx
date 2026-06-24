"use client";
import { useCallback, useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { apiGet, apiPost, ApiError } from "../lib/api";
import { PriorityBadge, TypeBadge, StatusBadge, fmtDate, WORK_STATUSES, STATUS_LABEL, COLUMN_ACCENT } from "../components/ui";
import type { Board, WorkItem, WorkItemStatus, WorkItemDetail } from "../lib/types";

export default function BoardPage() {
  return <AppShell><KanbanBoard /></AppShell>;
}

function KanbanBoard() {
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<WorkItemStatus | null>(null);
  const [selected, setSelected] = useState<WorkItemDetail | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setBoard(await apiGet<Board>("/api/work-items/board")); }
    catch { setError("Failed to load the board."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function move(item: WorkItem, to: WorkItemStatus) {
    if (item.status === to) return;
    // optimistic update
    setBoard((b) => {
      if (!b) return b;
      const cols: Board["columns"] = { ...b.columns };
      cols[item.status] = cols[item.status].filter((w) => w.id !== item.id);
      cols[to] = [{ ...item, status: to }, ...cols[to]];
      return { columns: cols };
    });
    try {
      await apiPost(`/api/work-items/${item.id}/status`, { status: to });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Status change failed.");
      load();
    }
  }

  async function open(id: number) {
    try { setSelected(await apiGet<WorkItemDetail>(`/api/work-items/${id}`)); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load work item."); }
  }

  const total = board ? Object.values(board.columns).reduce((n, c) => n + c.length, 0) : 0;

  return (
    <div className="container" style={{ maxWidth: 1400 }}>
      <div className="page-head">
        <h1>Board</h1>
        <span className="sub">{total} work item{total === 1 ? "" : "s"} · drag a card between columns or use its status menu.</span>
        <button className="btn sm right" onClick={load}>↻ Refresh</button>
      </div>

      {error && <div className="banner error" style={{ margin: "12px 0" }}>{error}</div>}

      {loading ? (
        <div className="loading-wrap"><span className="spinner" /> Loading board…</div>
      ) : total === 0 ? (
        <div className="card empty">
          <div className="big">🗂️</div>
          <div><b>No work items yet.</b></div>
          <div className="muted">Approve a candidate in the Review Queue to create your first work item.</div>
        </div>
      ) : (
        <div className="board">
          {WORK_STATUSES.map((st) => {
            const col = board!.columns[st] ?? [];
            return (
              <div
                key={st}
                className={`column${dragOver === st ? " drop" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setDragOver(st); }}
                onDragLeave={() => setDragOver((d) => (d === st ? null : d))}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(null);
                  const id = Number(e.dataTransfer.getData("text/plain"));
                  const item = findItem(board!, id);
                  if (item) move(item, st);
                }}
              >
                <div className="col-head" style={{ borderBottom: `2px solid ${COLUMN_ACCENT[st]}` }}>
                  {STATUS_LABEL[st]}
                  <span className="count">{col.length}</span>
                </div>
                <div className="col-body">
                  {col.map((wi) => (
                    <article
                      key={wi.id}
                      className="wi-card"
                      draggable
                      onClick={() => open(wi.id)}
                      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(wi.id))}
                    >
                      <div className="title">{wi.title || <span className="faint">untitled</span>}</div>
                      <div className="meta">
                        <TypeBadge type={wi.type} />
                        <PriorityBadge priority={wi.priority} />
                        {wi.due_date && <span className="badge">due {fmtDate(wi.due_date)}</span>}
                      </div>
                      <div className="row" style={{ marginTop: 9, gap: 6 }}>
                        <span className="id">WI-{wi.id}</span>
                        <select
                          className="select"
                          style={{ width: "auto", padding: "3px 6px", fontSize: 12, marginLeft: "auto" }}
                          value={wi.status}
                          aria-label={`Status for work item ${wi.id}`}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => move(wi, e.target.value as WorkItemStatus)}
                        >
                          {WORK_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                        </select>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {selected && (
        <WorkItemDrawer
          detail={selected}
          onClose={() => setSelected(null)}
          onChanged={(updated) => { setSelected(updated); load(); }}
        />
      )}
    </div>
  );
}

function WorkItemDrawer({ detail, onClose, onChanged }: {
  detail: WorkItemDetail; onClose: () => void; onChanged: (d: WorkItemDetail) => void;
}) {
  const wi = detail.work_item;
  const [busy, setBusy] = useState(false);

  async function changeStatus(to: WorkItemStatus) {
    if (to === wi.status) return;
    setBusy(true);
    try {
      await apiPost(`/api/work-items/${wi.id}/status`, { status: to });
      onChanged({ ...detail, work_item: { ...wi, status: to } });
    } catch { setBusy(false); }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="dh">
          <StatusBadge status={wi.status} />
          <h2 style={{ flex: 1 }}>WI-{wi.id}</h2>
          <button className="btn ghost sm" onClick={onClose}>✕</button>
        </div>
        <div className="db">
          <h3>{wi.title || <span className="faint">untitled</span>}</h3>
          {wi.summary && <div className="muted">{wi.summary}</div>}
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <TypeBadge type={wi.type} />
            <PriorityBadge priority={wi.priority} />
            {wi.due_date && <span className="badge">due {fmtDate(wi.due_date)}</span>}
          </div>
          <div className="kv">
            <span className="k">Status</span>
            <span>
              <select className="select" style={{ width: "auto" }} value={wi.status} disabled={busy}
                onChange={(e) => changeStatus(e.target.value as WorkItemStatus)}>
                {WORK_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
              </select>
            </span>
            <span className="k">Assignees</span>
            <span>{detail.assignees.length
              ? detail.assignees.map((a) => `${a.display_name || (a.telegram_username ? "@" + a.telegram_username : `#${a.assignee_id}`)}${a.is_primary ? " (primary)" : ""}`).join(", ")
              : <span className="faint">unassigned</span>}</span>
            <span className="k">Labels</span>
            <span>{detail.labels.length ? detail.labels.map((l) => l.name).join(", ") : <span className="faint">none</span>}</span>
            <span className="k">From candidate</span><span className="mono">#{wi.source_candidate_id}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function findItem(board: Board, id: number): WorkItem | undefined {
  for (const col of Object.values(board.columns)) {
    const hit = col.find((w) => w.id === id);
    if (hit) return hit;
  }
  return undefined;
}
