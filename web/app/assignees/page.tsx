"use client";
import { useCallback, useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { apiGet, apiPost, apiPatch, ApiError } from "../lib/api";
import type { Assignee } from "../lib/types";

export default function AssigneesPage() {
  return <AppShell><Assignees /></AppShell>;
}

function Assignees() {
  const [items, setItems] = useState<Assignee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Assignee | "new" | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setItems(await apiGet<Assignee[]>("/api/assignees")); }
    catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? "Managing assignees requires an admin account." : "Failed to load assignees.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function toggleActive(a: Assignee) {
    try { await apiPatch(`/api/assignees/${a.id}`, { is_active: !a.is_active }); load(); }
    catch { setError("Could not update assignee."); }
  }

  return (
    <div className="container">
      <div className="page-head">
        <h1>Assignees</h1>
        <span className="sub">People the extractor can resolve from Telegram names and aliases.</span>
        <button className="btn primary sm right" onClick={() => setEditing("new")}>+ New assignee</button>
      </div>

      {error && <div className="banner error" style={{ margin: "12px 0" }}>{error}</div>}

      <div className="card" style={{ marginTop: 12 }}>
        {loading ? (
          <div className="loading-wrap"><span className="spinner" /> Loading…</div>
        ) : items.length === 0 ? (
          <div className="empty"><div className="big">👤</div><div><b>No assignees yet.</b></div>
            <div className="muted">Add the people who appear in your Telegram chats.</div></div>
        ) : (
          <table className="tbl">
            <thead><tr><th>Name</th><th>Telegram</th><th>Aliases</th><th>Linked user</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td style={{ fontWeight: 600 }}>{a.display_name || <span className="faint">—</span>}</td>
                  <td className="muted">{a.telegram_username ? `@${a.telegram_username}` : <span className="faint">—</span>}</td>
                  <td>{a.aliases?.length ? <span className="chips">{a.aliases.map((x) => <span key={x} className="badge">{x}</span>)}</span> : <span className="faint">—</span>}</td>
                  <td className="muted">{a.user_id ? `user #${a.user_id}` : <span className="faint">—</span>}</td>
                  <td><span className={`badge ${a.is_active ? "st-done" : "st-rejected"}`}>{a.is_active ? "active" : "inactive"}</span></td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button className="btn ghost sm" onClick={() => setEditing(a)}>Edit</button>
                    <button className="btn ghost sm" onClick={() => toggleActive(a)}>{a.is_active ? "Deactivate" : "Activate"}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing && (
        <AssigneeDrawer
          assignee={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}

function AssigneeDrawer({ assignee, onClose, onSaved }: {
  assignee: Assignee | null; onClose: () => void; onSaved: () => void;
}) {
  const [displayName, setDisplayName] = useState(assignee?.display_name ?? "");
  const [username, setUsername] = useState(assignee?.telegram_username ?? "");
  const [aliases, setAliases] = useState((assignee?.aliases ?? []).join(", "));
  const [active, setActive] = useState(assignee?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true); setError(null);
    const payload = {
      display_name: displayName || null,
      telegram_username: username || null,
      aliases: aliases.split(",").map((s) => s.trim()).filter(Boolean),
      is_active: active,
    };
    try {
      if (assignee) await apiPatch(`/api/assignees/${assignee.id}`, payload);
      else await apiPost("/api/assignees", payload);
      onSaved();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Save failed."); setBusy(false); }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="dh">
          <h2 style={{ flex: 1 }}>{assignee ? `Edit assignee #${assignee.id}` : "New assignee"}</h2>
          <button className="btn ghost sm" onClick={onClose}>✕</button>
        </div>
        <div className="db">
          {error && <div className="banner error">{error}</div>}
          <label className="field">Display name
            <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} autoFocus />
          </label>
          <label className="field">Telegram username
            <input className="input" value={username} placeholder="without @" onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label className="field">Aliases <span className="faint" style={{ fontWeight: 400 }}>(comma-separated)</span>
            <input className="input" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="Vanya, Иван" />
          </label>
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active
          </label>
          <div className="row" style={{ paddingTop: 4 }}>
            <button className="btn primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
            <button className="btn" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}
