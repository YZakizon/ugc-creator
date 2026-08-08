import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "../app/providers";
import { RenderNodeSettings } from "../components/render-node-settings";

describe("render node settings", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("creates a ComfyUI render node", async () => {
    let submitted: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        submitted = JSON.parse(String(init.body));
        return new Response(JSON.stringify({ id: "node-1", ...submitted, provider: "comfyui", health_status: "unknown", health_message: null, health_checked_at: null, created_at: "2026-08-08T00:00:00Z", updated_at: "2026-08-08T00:00:00Z" }), { status: 201, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
    });

    render(<Providers><RenderNodeSettings /></Providers>);
    fireEvent.change(screen.getByLabelText("Node name"), { target: { value: "GPU workstation" } });
    fireEvent.change(screen.getByLabelText("ComfyUI URL"), { target: { value: "http://host.docker.internal:8188" } });
    fireEvent.click(screen.getByRole("button", { name: "Add render node" }));

    await waitFor(() => expect(screen.getByText("Render node saved.")).toBeInTheDocument());
    expect(submitted).toMatchObject({ name: "GPU workstation", base_url: "http://host.docker.internal:8188", is_active: true });
  });
});
