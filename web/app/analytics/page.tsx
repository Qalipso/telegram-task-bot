"use client";
import { useCallback, useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { apiGet, ApiError } from "../lib/api";
import type { AnalyticsOverview } from "../lib/types";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";

const C = {
  accent: "#2a5bd7",
  success: "#1f9d57",
  danger: "#d23b3b",
  warn: "#c4810b",
  gray: "#888780",
  grid: "#e1e5ea",
  muted: "#5d6b78",
};
const STATUS_COLORS: Record<string, string> = {
  inbox: C.accent, backlog: "#85B7EB", ready: C.success, in_progress: "#378ADD",
  blocked: C.danger, review: C.warn, done: C.success, cancelled: C.gray, archived: C.gray,
};

export default function AnalyticsPage() {
  return <AppShell><Analytics /></AppShell>;
}

function Analytics() {
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setData(await apiGet<AnalyticsOverview>("/api/analytics/overview?days=14"));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403
        ? "Analytics requires an admin account."
        : "Failed to load analytics.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="container">
      <div className="page-head">
        <h1>Analytics</h1>
        <span className="sub">Capture funnel, throughput, and workload across all chats.</span>
        <div className="right row" style={{ gap: 8 }}>
          <button className="btn sm" onClick={load}>↻ Refresh</button>
        </div>
      </div>

      {error && <div className="banner error" style={{ margin: "12px 0" }}>{error}</div>}

      {loading ? (
        <div className="loading-wrap"><span className="spinner" /> Loading…</div>
      ) : data ? (
        <>
          <div className="row" style={{ gap: 12, flexWrap: "wrap", marginTop: 12 }}>
            <Kpi label="Total tasks" value={data.kpis.tasks_total} />
            <Kpi label="Active" value={data.kpis.tasks_active} />
            <Kpi label="Overdue" value={data.kpis.tasks_overdue} tone={data.kpis.tasks_overdue ? "danger" : undefined} />
            <Kpi label="Done" value={data.kpis.tasks_done} />
            <Kpi label="Approval rate" value={pct(data.kpis.approval_rate)} tone="success" />
            <Kpi label="Avg AI confidence" value={data.kpis.avg_extraction_confidence.toFixed(2)} />
          </div>

          <div className="row" style={{ gap: 14, flexWrap: "wrap", alignItems: "stretch", marginTop: 18 }}>
            <ChartCard title="Task flow · 14 days" style={{ flex: 2, minWidth: 320 }}>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={data.tasks_over_time} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} fontSize={11} stroke={C.muted} />
                  <YAxis allowDecimals={false} fontSize={11} stroke={C.muted} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Area type="monotone" dataKey="candidates" name="Candidates" stroke={C.accent} fill={C.accent} fillOpacity={0.12} strokeWidth={2} />
                  <Area type="monotone" dataKey="approved" name="Approved" stroke={C.success} fill={C.success} fillOpacity={0.1} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Task status" style={{ flex: 1, minWidth: 240 }}>
              {data.status_distribution.length ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={data.status_distribution} dataKey="count" nameKey="status" innerRadius={48} outerRadius={78} paddingAngle={2}>
                      {data.status_distribution.map((s) => <Cell key={s.status} fill={STATUS_COLORS[s.status] ?? C.gray} />)}
                    </Pie>
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : <Empty />}
            </ChartCard>
          </div>

          <div className="row" style={{ gap: 14, flexWrap: "wrap", alignItems: "stretch", marginTop: 14 }}>
            <ChartCard title="Extraction funnel" style={{ flex: 1, minWidth: 300 }}>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={funnelRows(data)} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="stage" fontSize={11} stroke={C.muted} />
                  <YAxis allowDecimals={false} fontSize={11} stroke={C.muted} />
                  <Tooltip />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {funnelRows(data).map((r) => <Cell key={r.stage} fill={r.color} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="AI confidence distribution" style={{ flex: 1, minWidth: 300 }}>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={data.confidence_histogram} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} vertical={false} />
                  <XAxis dataKey="bucket" fontSize={11} stroke={C.muted} />
                  <YAxis allowDecimals={false} fontSize={11} stroke={C.muted} />
                  <Tooltip />
                  <Bar dataKey="count" fill={C.accent} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>

          <ChartCard title="Workload by assignee" style={{ marginTop: 14 }}>
            {data.assignee_workload.length ? (
              <ResponsiveContainer width="100%" height={Math.max(120, data.assignee_workload.length * 38 + 30)}>
                <BarChart data={data.assignee_workload.map((w) => ({ ...w, closed: w.total - w.active }))} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
                  <CartesianGrid stroke={C.grid} horizontal={false} />
                  <XAxis type="number" allowDecimals={false} fontSize={11} stroke={C.muted} />
                  <YAxis type="category" dataKey="name" width={110} fontSize={12} stroke={C.muted} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="active" name="Active" stackId="a" fill={C.accent} radius={[0, 0, 0, 0]} />
                  <Bar dataKey="closed" name="Closed" stackId="a" fill={C.gray} />
                </BarChart>
              </ResponsiveContainer>
            ) : <Empty msg="No assigned tasks yet." />}
          </ChartCard>
        </>
      ) : null}
    </div>
  );
}

function funnelRows(d: AnalyticsOverview) {
  return [
    { stage: "Messages", count: d.funnel.messages, color: "#B5D4F4" },
    { stage: "Candidates", count: d.funnel.candidates, color: C.accent },
    { stage: "Approved", count: d.funnel.approved, color: C.success },
    { stage: "Rejected", count: d.funnel.rejected, color: C.danger },
  ];
}

function pct(v: number) { return `${Math.round(v * 100)}%`; }

function Kpi({ label, value, tone }: { label: string; value: number | string; tone?: "danger" | "success" }) {
  const color = tone === "danger" ? C.danger : tone === "success" ? C.success : undefined;
  return (
    <div className="card pad" style={{ minWidth: 140, flex: 1 }}>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color }}>{value}</div>
    </div>
  );
}

function ChartCard({ title, style, children }: { title: string; style?: React.CSSProperties; children: React.ReactNode }) {
  return (
    <div className="card pad" style={style}>
      <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  );
}

function Empty({ msg = "No data yet." }: { msg?: string }) {
  return <div className="empty" style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center" }}>
    <span className="faint">{msg}</span>
  </div>;
}
