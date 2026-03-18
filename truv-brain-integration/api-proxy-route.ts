/**
 * TruvBrain — Optional API Proxy Route
 * =====================================
 * Drop this into: TruvBrain/app/api/productivity/[...path]/route.ts
 *
 * This proxies all /api/productivity/* requests from the Next.js frontend
 * to the running api_server.py, so the dashboard can make same-origin
 * requests instead of cross-origin ones (avoids CORS issues in production).
 *
 * Usage in the dashboard:
 *   Set apiBaseUrl="/api/productivity" to use the proxy,
 *   or keep "http://localhost:8000" for direct local access.
 *
 * To use this route, set in TruvBrain/.env.local:
 *   PRODUCTIVITY_FRIEND_API_URL=http://localhost:8000
 *   (server-side, no NEXT_PUBLIC_ prefix needed for the proxy)
 */

import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.PRODUCTIVITY_FRIEND_API_URL || "http://localhost:8000";

async function proxyRequest(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  const path = params.path.join("/");
  const url = new URL(request.url);
  const targetUrl = `${API_BASE}/api/${path}${url.search}`;

  try {
    const body = request.method !== "GET" && request.method !== "HEAD"
      ? await request.text()
      : undefined;

    const upstream = await fetch(targetUrl, {
      method: request.method,
      headers: {
        "Content-Type": "application/json",
        // Forward auth header if present
        ...(request.headers.get("authorization")
          ? { Authorization: request.headers.get("authorization")! }
          : {}),
      },
      body,
      // Don't follow redirects automatically
      redirect: "manual",
    });

    const data = await upstream.text();
    return new NextResponse(data, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error: any) {
    return NextResponse.json(
      { error: "Productivity-Friend API unreachable", detail: error.message },
      { status: 502 }
    );
  }
}

export const GET    = proxyRequest;
export const POST   = proxyRequest;
export const PUT    = proxyRequest;
export const DELETE = proxyRequest;
