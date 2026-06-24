"use client";
/* Auth gate + top navigation. Fetches the current user once; redirects to /login
   on 401. Wrap every protected page in <AppShell>. */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { User } from "../lib/types";

const TABS = [
  { href: "/review", label: "Review Queue" },
  { href: "/board", label: "Board" },
  { href: "/assignees", label: "Assignees" },
  { href: "/sync", label: "Sync" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    apiGet<User>("/api/auth/me")
      .then((u) => { setUser(u); setState("ready"); })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else setState("error");
      });
  }, [router]);

  async function logout() {
    try { await apiPost("/api/auth/logout"); } catch { /* ignore */ }
    router.replace("/login");
  }

  if (state === "loading") {
    return <div className="loading-wrap"><span className="spinner" /> Loading…</div>;
  }
  if (state === "error") {
    return <div className="container"><div className="banner error">Could not reach the API. Is the backend running?</div></div>;
  }

  return (
    <>
      <nav className="nav">
        <span className="brand"><span className="dot" /> Work Intelligence</span>
        {TABS.map((t) => (
          <Link key={t.href} href={t.href} className={`tab${pathname.startsWith(t.href) ? " active" : ""}`}>
            {t.label}
          </Link>
        ))}
        <span className="spacer" />
        {user && (
          <span className="who">
            <b>{user.display_name || user.email}</b> · {user.role}
          </span>
        )}
        <button className="btn sm" onClick={logout}>Sign out</button>
      </nav>
      {children}
    </>
  );
}
