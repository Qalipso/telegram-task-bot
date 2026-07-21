"use client";
/* Auth gate + top navigation. Fetches the current user once; redirects to /login
   on 401. Wrap every protected page in <AppShell>. */
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { apiGet, apiPost, ApiError } from "../lib/api";
import { Icon } from "./ui";
import type { User } from "../lib/types";

const TABS = [
  { href: "/review", label: "Review Queue" },
  { href: "/board", label: "Board" },
  { href: "/analytics", label: "Analytics" },
  { href: "/assignees", label: "Assignees" },
  { href: "/sync", label: "Sync" },
];

function isActive(href: string, pathname: string) {
  return pathname === href || pathname.startsWith(href + "/");
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [logoutState, setLogoutState] = useState<"idle" | "busy" | "error">("idle");

  useEffect(() => {
    apiGet<User>("/api/auth/me")
      .then((u) => { setUser(u); setState("ready"); })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else setState("error");
      });
  }, [router]);

  async function logout() {
    setLogoutState("busy");
    try {
      await apiPost("/api/auth/logout");
      router.replace("/login");
    } catch {
      setLogoutState("error");
    }
  }

  if (state === "loading") {
    return <div className="loading-wrap"><span className="spinner" /> Loading…</div>;
  }
  if (state === "error") {
    return (
      <div className="container">
        <div className="banner error">Unable to reach the API. Please refresh the page.</div>
      </div>
    );
  }

  return (
    <>
      <nav className="nav">
        <span className="brand">
          <Icon name="logo" size={18} aria-hidden />
          Work Intelligence
        </span>
        {TABS.map((t) => {
          const active = isActive(t.href, pathname);
          return (
            <Link
              key={t.href}
              href={t.href}
              className={`tab${active ? " active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              {t.label}
            </Link>
          );
        })}
        <span className="spacer" />
        {user && (
          <span className="who">
            <b>{user.display_name || user.email}</b> · {user.role}
          </span>
        )}
        {logoutState === "error" && (
          <span style={{ color: "var(--danger)", fontSize: 12 }}>Sign out failed</span>
        )}
        <button
          className="btn sm"
          onClick={logout}
          disabled={logoutState === "busy"}
        >
          {logoutState === "busy" ? <><span className="spinner sm" /> Signing out…</> : "Sign out"}
        </button>
      </nav>
      {children}
    </>
  );
}
