"use client";
import { useCallback, useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { apiGet, apiPost, ApiError } from "../lib/api";
import { StatusBadge, fmtDateTime } from "../components/ui";
import type { SyncStatus, SyncRun } from "../lib/types";

export default function SyncPage() {
  return <AppShell><Sync /></AppShell>;
}

function Sync() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [history, setHistory] = useState<SyncRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [s, h] = await Promise.all([
        apiGet<SyncStatus>("/api/sync/status"),
        apiGet<SyncRun[]>("/api/sync/history?limit=20"),
      ]);
      setStatus(s); setHistory(h);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? "Sync control requires an admin account." : "Failed to load sync status.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function runSync() {
    setBusy(true); setBanner(null); setError(null);
    try {
      const r = await apiPost<{ status: string; chat_id: number; queue_length: number }>("/api/sync/run", {});
      setBanner(`Sync queued for chat ${r.chat_id} · queue length ${r.queue_length}. The worker will process it shortly.`);
      setTimeout(load, 1200);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not trigger sync.");
    } finally { setBusy(false); }
  }

  return (
    <div className="container">
      <div className="page-head">
        <h1>Sync</h1>
        <span className="sub">Telegram ingestion status and run history.</span>
        <div className="right row" style={{ gap: 8 }}>
          <button className="btn sm" onClick={load}>↻ Refresh</button>
          <button className="btn primary sm" onClick={runSync} disabled={busy}>{busy ? "Queuing…" : "Run sync now"}</button>
        </div>
      </div>

      {banner && <div className="banner ok" style={{ margin: "12px 0" }}>{banner}</div>}
      {error && <div className="banner error" style={{ margin: "12px 0" }}>{error}</div>}

      {loading ? (
        <div className="loading-wrap"><span className="spinner" /> Loading…</div>
      ) : (
        <>
          <div className="row" style={{ gap: 14, alignItems: "stretch", marginTop: 12, flexWrap: "wrap" }}>
            <div className="card pad" style={{ minWidth: 160 }}>
              <div className="muted" style={{ fontSize: 12 }}>Queue length</div>
              <div style={{ fontSize: 30, fontWeight: 700 }}>{status?.queue_length ?? 0}</div>
            </div>
            <div className="card pad" style={{ flex: 1, minWidth: 280 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Latest run</div>
              {status?.latest_run ? <RunLine run={status.latest_run} /> : <span className="faint">No runs yet.</span>}
            </div>
          </div>

          <h2 style={{ margin: "26px 0 10px" }}>Tracked chats</h2>
          <div className="card">
            {status?.states.length ? (
              <table className="tbl">
                <thead><tr><th>Chat ID</th><th>Last message ID</th><th>Last successful sync</th><th>Last error</th></tr></thead>
                <tbody>
                  {status.states.map((s) => (
                    <tr key={s.chat_id}>
                      <td className="mono">{s.chat_id}</td>
                      <td className="mono">{s.last_external_message_id ?? "—"}</td>
                      <td className="muted">{fmtDateTime(s.last_successful_sync_at)}</td>
                      <td>{s.last_error ? <span className="badge st-rejected">{s.last_error}</span> : <span className="faint">none</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="empty"><div className="muted">No chats tracked yet.</div></div>}
          </div>

          <h2 style={{ margin: "26px 0 10px" }}>Run history</h2>
          <div className="card">
            {history.length ? (
              <table className="tbl">
                <thead><tr><th>Run</th><th>Trigger</th><th>Status</th><th>Read</th><th>Saved</th><th>Started</th><th>Finished</th></tr></thead>
                <tbody>
                  {history.map((r) => (
                    <tr key={r.id}>
                      <td className="mono">#{r.id}</td>
                      <td className="muted">{r.trigger_type}</td>
                      <td><StatusBadge status={r.status} /></td>
                      <td>{r.messages_read ?? "—"}</td>
                      <td>{r.messages_saved ?? "—"}</td>
                      <td className="muted">{fmtDateTime(r.started_at)}</td>
                      <td className="muted">{fmtDateTime(r.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="empty"><div className="muted">No sync runs recorded yet. Trigger one above.</div></div>}
          </div>
        </>
      )}
    </div>
  );
}

function RunLine({ run }: { run: SyncRun }) {
  return (
    <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
      <span className="mono">#{run.id}</span>
      <StatusBadge status={run.status} />
      <span className="muted">{run.messages_saved ?? 0} saved / {run.messages_read ?? 0} read</span>
      <span className="faint">· {fmtDateTime(run.finished_at ?? run.started_at)}</span>
      {run.error_message && <span className="badge st-rejected">{run.error_message}</span>}
    </div>
  );
}
