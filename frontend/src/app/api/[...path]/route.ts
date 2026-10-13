// Proxies /api/* to the FastAPI backend, streaming responses through unchanged
// (the chat endpoint answers with server-sent events).
import type { NextRequest } from "next/server";

const BACKEND_URL = () => process.env.BACKEND_URL ?? "http://localhost:8000";

async function proxy(request: NextRequest, ctx: RouteContext<"/api/[...path]">) {
  const { path } = await ctx.params;
  const target = `${BACKEND_URL()}/api/${path.join("/")}${request.nextUrl.search}`;
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers: forwardedHeaders(request),
      body: request.method === "GET" ? undefined : await request.text(),
      cache: "no-store",
    });
    const headers = new Headers();
    for (const name of ["content-type", "x-legal-disclaimer", "cache-control"]) {
      const value = upstream.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch {
    return Response.json({ detail: "The backend is not reachable. Is it running?" }, { status: 502 });
  }
}

function forwardedHeaders(request: NextRequest): Headers {
  const headers = new Headers({ "content-type": request.headers.get("content-type") ?? "application/json" });
  const authorization = request.headers.get("authorization");
  if (authorization) headers.set("authorization", authorization);
  // The backend rate-limits per client, so it needs the client's address, not the proxy's.
  const client = request.headers.get("x-forwarded-for") ?? request.headers.get("x-real-ip");
  if (client) headers.set("x-forwarded-for", client);
  return headers;
}

export const GET = proxy;
export const POST = proxy;
