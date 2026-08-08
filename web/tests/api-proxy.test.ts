import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PUT } from "../app/api/[...path]/route";

describe("API proxy", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("forwards workflow update PUT requests to the API", async () => {
    const payload = JSON.stringify({ name: "Updated workflow", workflow_json: {} });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "workflow-1", name: "Updated workflow" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const request = {
      method: "PUT",
      nextUrl: { search: "" },
      headers: new Headers({ "content-type": "application/json" }),
      arrayBuffer: async () => new TextEncoder().encode(payload).buffer,
    } as NextRequest;

    const response = await PUT(request, {
      params: { path: ["v1", "workflow-templates", "workflow-1"] },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/workflow-templates/workflow-1",
      expect.objectContaining({ method: "PUT", cache: "no-store" }),
    );
    const forwardedRequest = fetchMock.mock.calls[0]?.[1];
    expect(new TextDecoder().decode(forwardedRequest?.body as ArrayBuffer)).toBe(payload);
    expect(response.status).toBe(200);
  });
});
