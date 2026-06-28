"use client";
import { useCallback, useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { apiGet, apiPost, ApiError } from "../lib/api";
import { Drawer } from "../components/Drawer";
import {
  PriorityBadge, TypeBadge, StatusBadge, fmtDate, Icon,
  WORK_STATUSES, STATUS_LABEL, COLUMN_ACCENT, PRIORITY_LABEL,
} from "../components/ui";
import type { Board, WorkItem, WorkItemStatus, WorkItemDetail, Priority, CandidateType, Label } from "../lib/types";

const LABEL_PALETTE = ["#4DA2FF", "#1f9d57", "#c4810b", "#7a52c4", "#d9534f", "#2a8bd7"];

const TERMINAL: WorkItemStatus[] = ["inbox", "cancelled", "archived"];
const PRIORITIES: Priority[] = ["critical", "high", "medium", "low"];
const TYPES: CandidateType[] = ["task", "request", "reminder", "idea", "knowledge"];

export default function BoardPage() {
  return <AppShell><KanbanBoard /></AppShell>;
}

function KanbanBoard() {
  const [board, setBoard] = useState<Board | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<WorkItemStatus | null>(null);
  const [selected, setSelected] = useState<WorkItemDetail | null>(null);

  const [search, setSearch] = useState("");
  const [filterPriority, setFilterPriority] = useState<Priority | "">("");
  const [filterType, setFilterType] = useState<CandidateType | "">("");
  const [showTerminal, setShowTerminal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setBoard(await apiGet<Board>("/api/work-items/board")); }
    catch { setError("Failed to load the board."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  function matchItem(wi: WorkItem): boolean {
    if (search && !(wi.title ?? "").toLowerCase().includes(search.toLowerCase())) return false;
    if (filterPriority && wi.priority !== filterPriority) return false;
    if (filterType && wi.type !== filterType) return false;
    return true;
  }

  function clearFilters() { setSearch(""); setFilterPriority(""); setFilterType(""); }

  const hasFilter = !!(search || filterPriority || filterType);
  const total = board ? Object.values(board.columns).reduce((n, c) => n + c.length, 0) : 0;
  const matchTotal = board
    ? Object.values(board.columns).reduce((n, c) => n + c.filter(matchItem).length, 0)
    : 0;

  const visibleStatuses = WORK_STATUSES.filter((st) => {
    if (!TERMINAL.includes(st)) return true;
    const col = board?.columns[st] ?? [];
    return showTerminal || col.length > 0;
  });

  async function move(item: WorkItem, to: WorkItemStatus) {
    if (item.status === to) return;
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

  const chipStyle = (active: boolean): React.CSSProperties =>
    active ? { background: "var(--accent-soft)", color: "var(--accent-ink)", borderColor: "var(--accent-200)" } : {};

  return (
    <div className="container" style={{ maxWidth: 1400 }}>
      <div className="page-head">
        <h1>Board</h1>
        <span className="sub">
          {hasFilter ? `${matchTotal} of ${total}` : total} work item{total === 1 ? "" : "s"}
          {!hasFilter && " · drag a card or use its status menu"}
        </span>
        <button className="btn sm right" onClick={load}>
          <Icon name="refresh" size={13} aria-hidden /> Refresh
        </button>
      </div>

      {error && <div className="banner error" role="alert" style={{ margin: "12px 0" }}>{error}</div>}

      {!loading && total > 0 && (
        <div className="toolbar">
          <input
            className="input"
            style={{ width: 200, padding: "5px 10px", fontSize: 13 }}
            placeholder="Search items…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search work items"
          />
          {PRIORITIES.map((p) => (
            <button
              key={p}
              className="btn sm"
              style={chipStyle(filterPriority === p)}
              onClick={() => setFilterPriority(filterPriority === p ? "" : p)}
              aria-pressed={filterPriority === p}
            >
              {PRIORITY_LABEL[p]}
            </button>
          ))}
          <select
            className="select"
            style={{ width: "auto", padding: "5px 10px", fontSize: 13 }}
            value={filterType}
            onChange={(e) => setFilterType(e.target.value as CandidateType | "")}
            aria-label="Filter by type"
          >
            <option value="">All types</option>
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          {hasFilter && (
            <button className="btn sm ghost" onClick={clearFilters}>
              <Icon name="close" size={11} aria-hidden /> Clear
            </button>
          )}
          <button
            className="btn sm ghost right"
            onClick={() => setShowTerminal((s) => !s)}
            aria-pressed={showTerminal}
          >
            {showTerminal ? "Hide empty cols" : "Show all cols"}
          </button>
        </div>
      )}

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
          {visibleStatuses.map((st) => {
            const col = board!.columns[st] ?? [];
            const filtered = col.filter(matchItem);
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
                  <span
                    className="count"
                    title={hasFilter && filtered.length !== col.length ? `${filtered.length} of ${col.length}` : undefined}
                  >
                    {hasFilter && filtered.length !== col.length
                      ? `${filtered.length}/${col.length}`
                      : col.length}
                  </span>
                </div>
                <div className="col-body">
                  {filtered.length === 0 && col.length > 0 ? (
                    <span className="faint" style={{ fontSize: 12, padding: "8px 2px", display: "block" }}>
                      No matches
                    </span>
                  ) : (
                    filtered.map((wi) => (
                      <article
                        key={wi.id}
                        className="wi-card"
                        draggable
                        tabIndex={0}
                        aria-label={`Open ${wi.title || "untitled"} (WI-${wi.id})`}
                        onClick={() => open(wi.id)}
                        onKeyDown={(e) => {
                          if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                            e.preventDefault();
                            open(wi.id);
                          }
                        }}
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
                            aria-label={`Status for WI-${wi.id}`}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => move(wi, e.target.value as WorkItemStatus)}
                          >
                            {WORK_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                          </select>
                        </div>
                      </article>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {selected && (
        <WorkItemDrawer
          key={selected.work_item.id}
          initial={selected}
          onClose={() => setSelected(null)}
          onBoardChanged={load}
        />
      )}
    </div>
  );
}

function WorkItemDrawer({ initial, onClose, onBoardChanged }: {
  initial: WorkItemDetail; onClose: () => void; onBoardChanged: () => void;
}) {
  const [detail, setDetail] = useState<WorkItemDetail>(initial);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<Label[]>([]);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const wi = detail.work_item;
  const titleId = `wi-${wi.id}-title`;

  useEffect(() => {
    apiGet<Label[]>("/api/labels").then(setCatalog).catch(() => {});
  }, []);

  async function refetch() {
    setDetail(await apiGet<WorkItemDetail>(`/api/work-items/${wi.id}`));
  }

  async function changeStatus(to: WorkItemStatus) {
    if (to === wi.status) return;
    setBusy(true); setErr(null);
    try {
      await apiPost(`/api/work-items/${wi.id}/status`, { status: to });
      setDetail({ ...detail, work_item: { ...wi, status: to } });
      onBoardChanged();
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Status change failed."); }
    finally { setBusy(false); }
  }

  async function assignLabel(labelId: number) {
    setBusy(true); setErr(null);
    try {
      await apiPost(`/api/work-items/${wi.id}/labels`, { label_id: labelId });
      await refetch();
      onBoardChanged();
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Could not add label."); }
    finally { setBusy(false); }
  }

  async function createAndAssign() {
    const name = newName.trim();
    if (!name) return;
    setBusy(true); setErr(null);
    try {
      const color = LABEL_PALETTE[catalog.length % LABEL_PALETTE.length];
      const created = await apiPost<Label>("/api/labels", { name, color });
      setCatalog((c) => [...c, created]);
      await apiPost(`/api/work-items/${wi.id}/labels`, { label_id: created.id });
      await refetch();
      onBoardChanged();
      setNewName(""); setAdding(false);
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Could not create label."); }
    finally { setBusy(false); }
  }

  const colorOf = (id: number, fallback: string | null) =>
    catalog.find((c) => c.id === id)?.color ?? fallback ?? "var(--accent)";
  const assignedIds = new Set(detail.labels.map((l) => l.id));
  const available = catalog.filter((c) => !assignedIds.has(c.id));

  return (
    <Drawer titleId={titleId} onClose={onClose}>
      <div className="dh">
        <StatusBadge status={wi.status} />
        <h2 id={titleId} style={{ flex: 1 }}>WI-{wi.id}</h2>
        <button className="btn ghost sm" onClick={onClose} aria-label="Close">
          <Icon name="close" size={14} aria-hidden />
        </button>
      </div>
      <div className="db">
        <h3>{wi.title || <span className="faint">untitled</span>}</h3>
        {wi.summary && <div className="muted">{wi.summary}</div>}
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          <TypeBadge type={wi.type} />
          <PriorityBadge priority={wi.priority} />
          {wi.due_date && <span className="badge">due {fmtDate(wi.due_date)}</span>}
        </div>

        {err && <div className="banner error" role="alert" style={{ margin: "10px 0" }}>{err}</div>}

        <div className="kv">
          <span className="k">Status</span>
          <span>
            <select className="select" style={{ width: "auto" }} value={wi.status} disabled={busy}
              onChange={(e) => changeStatus(e.target.value as WorkItemStatus)}>
              {WORK_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </span>

          <span className="k">Assignees</span>
          <span className="chip-row">
            {detail.assignees.length === 0 && <span className="faint">unassigned</span>}
            {detail.assignees.map((a) => (
              <span key={a.assignee_id} className={`assignee-chip${a.is_primary ? " primary" : ""}`}>
                <Icon name="user" size={11} aria-hidden />
                {a.display_name || (a.telegram_username ? "@" + a.telegram_username : `#${a.assignee_id}`)}
                {a.is_primary && <span className="faint"> · primary</span>}
              </span>
            ))}
          </span>

          <span className="k"><Icon name="tag" size={12} aria-hidden /> Labels</span>
          <span>
            <span className="chip-row">
              {detail.labels.length === 0 && <span className="faint">none</span>}
              {detail.labels.map((l) => (
                <span key={l.id} className="label-chip">
                  <span className="label-dot" style={{ background: colorOf(l.id, l.color) }} />
                  {l.name}
                </span>
              ))}
            </span>
            <span className="add-label-row">
              {available.length > 0 && (
                <select className="select" value="" disabled={busy}
                  style={{ width: "auto", padding: "3px 8px", fontSize: 12 }}
                  aria-label="Add an existing label"
                  onChange={(e) => { if (e.target.value) assignLabel(Number(e.target.value)); }}>
                  <option value="">+ Add label…</option>
                  {available.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              )}
              {!adding ? (
                <button className="btn sm ghost" onClick={() => setAdding(true)} disabled={busy}>
                  <Icon name="plus" size={11} aria-hidden /> New label
                </button>
              ) : (
                <>
                  <input className="input" autoFocus value={newName}
                    style={{ width: 130, padding: "4px 8px", fontSize: 12 }}
                    placeholder="Label name" aria-label="New label name"
                    onChange={(e) => setNewName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") { e.preventDefault(); createAndAssign(); }
                    }} />
                  <button className="btn sm primary" onClick={createAndAssign} disabled={busy || !newName.trim()}>
                    Create
                  </button>
                  <button className="btn sm ghost" onClick={() => { setAdding(false); setNewName(""); }} disabled={busy}>
                    Cancel
                  </button>
                </>
              )}
            </span>
          </span>

          <span className="k">From candidate</span>
          <span className="mono">#{wi.source_candidate_id}</span>
        </div>
      </div>
    </Drawer>
  );
}

function findItem(board: Board, id: number): WorkItem | undefined {
  for (const col of Object.values(board.columns)) {
    const hit = col.find((w) => w.id === id);
    if (hit) return hit;
  }
  return undefined;
}
