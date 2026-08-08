import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "../app/providers";
import { CreateBatchForm } from "../components/create-batch-form";

const profile = {
  id: "profile-1",
  name: "Elena Shelf",
  character_id: "character-1",
  voice_profile_id: "voice-1",
  renderer_provider: "comfyui",
  workflow_template_id: "workflow-1",
  is_active: true,
  created_at: "2026-08-07T12:00:00Z",
  updated_at: "2026-08-07T12:00:00Z",
};

describe("create batch form", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps submission disabled until profiles have loaded", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ items: [profile], total: 1 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }));

    render(<Providers><CreateBatchForm /></Providers>);
    const option = await screen.findByRole("option", { name: "Elena Shelf" });
    expect(option).toBeVisible();
    const submit = screen.getByRole("button", { name: "Create batch" });
    expect(submit).toBeDisabled();
  });

  it("normalizes multiline topics and persists the selected profile", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).includes("render-profiles")) {
        return new Response(JSON.stringify({ items: [profile], total: 1 }), { status: 200 });
      }
      expect(String(input)).toContain("/batches");
      expect(JSON.parse(String(init?.body))).toMatchObject({
        name: "Tuesday ideas",
        topics: ["First topic", "Second topic"],
        default_render_profile_id: "profile-1",
      });
      return new Response(JSON.stringify({ id: "batch-1" }), { status: 201 });
    });

    render(<Providers><CreateBatchForm /></Providers>);
    fireEvent.change(await screen.findByLabelText("Batch name"), { target: { value: "Tuesday ideas" } });
    fireEvent.change(screen.getByLabelText("Topics"), { target: { value: " First topic \n\n Second topic " } });
    fireEvent.change(screen.getByLabelText("Render profile"), { target: { value: "profile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create batch" }));

    await waitFor(() => expect(screen.getByText("Batch created successfully.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalled();
  });

  it("does not offer profiles without an assigned voice", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      items: [{ ...profile, voice_profile_id: null }],
      total: 1,
    }), { status: 200, headers: { "content-type": "application/json" } }));

    render(<Providers><CreateBatchForm /></Providers>);

    expect(await screen.findByText("Connect a voice to a render profile before creating a batch.")).toBeVisible();
    expect(screen.queryByRole("option", { name: "Elena Shelf" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create batch" })).toBeDisabled();
  });
});
