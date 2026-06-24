/* Same-origin proxy: forwards /api/* from the browser to the FastAPI backend,
   passing the session cookie through in both directions so httpOnly auth works.
   In Docker API_BASE=http://api:8000; locally it defaults to localhost:8000. */
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const target = `${API_BASE}/api/${path.join("/")}${req.nextUrl.search}`;

  const headers: Record<string, string> = {};
  const cookie = req.headers.get("cookie");
  if (cookie) headers["cookie"] = cookie;
  const contentType = req.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;

  const init: RequestInit = { method: req.method, headers, redirect: "manual" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch {
    return NextResponse.json(
      { detail: "Backend API is unreachable", target },
      { status: 502 },
    );
  }

  const res = new NextResponse(await upstream.arrayBuffer(), { status: upstream.status });
  const respType = upstream.headers.get("content-type");
  if (respType) res.headers.set("content-type", respType);
  for (const c of upstream.headers.getSetCookie?.() ?? []) {
    res.headers.append("set-cookie", c);
  }
  return res;
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
