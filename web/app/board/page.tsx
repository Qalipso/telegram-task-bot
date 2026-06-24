"use client";
import { useCallback, useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { apiGet, apiPost, ApiError } from "../lib/api";
import { PriorityBadge, TypeBadge, fmtDate, WORK_STATUSES, STATUS_LABEL, COLUMN_ACCENT } from "../components/ui";
import type { Board, WorkItem, WorkItemStatus } from "../lib/types";

export default function BoardPage() {
  return <AppShell><KanbanBoard /></AppShell>;
}

function KanbanBoard() {
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<WorkItemStatus | null>(null);

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
