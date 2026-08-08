import { NextRequest, NextResponse } from "next/server";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

async function proxy(request: NextRequest, path: string[]) {
  // Next's catch-all params normally omit the route's `/api` segment, but
  // normalize it defensively so browser integration requests never become
  // `/api/api/v1/...` when the runtime includes the prefix.
  const apiPath = path[0] === "api" ? path.slice(1) : path;
  const target = `${apiBaseUrl.replace(/\/$/, "")}/api/${apiPath.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }

  const body = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : await request.arrayBuffer();
  const response = await fetch(target, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
  });

  return new NextResponse(response.body, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function GET(
  request: NextRequest,
  context: { params: { path: string[] } },
) {
  return proxy(request, context.params.path);
}

export async function POST(
  request: NextRequest,
  context: { params: { path: string[] } },
) {
  return proxy(request, context.params.path);
}

export async function PATCH(
  request: NextRequest,
  context: { params: { path: string[] } },
) {
  return proxy(request, context.params.path);
}

export async function PUT(
  request: NextRequest,
  context: { params: { path: string[] } },
) {
  return proxy(request, context.params.path);
}

export async function DELETE(
  request: NextRequest,
  context: { params: { path: string[] } },
) {
  return proxy(request, context.params.path);
}
