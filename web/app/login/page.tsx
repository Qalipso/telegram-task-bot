"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "../lib/api";
import type { User } from "../lib/types";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiPost<User>("/api/auth/login", { email, password });
      router.replace("/review");
    } catch {
      setError("Invalid email or password.");
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <form className="card pad" onSubmit={submit} style={{ width: 360, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: 18 }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: "var(--accent)" }} />
            Work Intelligence
          </div>
          <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>Sign in to review and triage work items.</div>
        </div>
        {error && <div className="banner error">{error}</div>}
        <label className="field">
          Email
          <input className="input" type="email" autoComplete="username" value={email}
            onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </label>
        <label className="field">
          Password
          <input className="input" type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <button className="btn primary" type="submit" disabled={busy} style={{ justifyContent: "center" }}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
