"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost } from "../lib/api";
import { Icon } from "../components/ui";
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
    <div className="login-wrap">
      <div className="login-glow" aria-hidden="true" />
      <form className="card login-card" onSubmit={submit}>
        <div className="login-brand">
          <Icon name="logo" size={20} aria-hidden />
          <h1>Work Intelligence</h1>
        </div>
        <p className="login-sub">Sign in to review and triage work items.</p>
        {error && (
          <div className="banner error" role="alert">{error}</div>
        )}
        <label className="field">
          Email
          <input
            className="input"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label className="field">
          Password
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <button className="btn primary" type="submit" disabled={busy} style={{ justifyContent: "center" }}>
          {busy ? <><span className="spinner sm" /> Signing in…</> : "Sign in"}
        </button>
      </form>
    </div>
  );
}
