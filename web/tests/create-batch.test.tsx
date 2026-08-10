import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "../app/providers";
import { CreateTopicForm } from "../components/create-batch-form";

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

describe("create topic form", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps submission disabled until profiles have loaded", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ items: [profile], total: 1 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }));

    render(<Providers><CreateTopicForm /></Providers>);
    const option = await screen.findByRole("option", { name: "Elena Shelf" });
    expect(option).toBeVisible();
    const submit = screen.getByRole("button", { name: "Create topic" });
    expect(submit).toBeDisabled();
  });

  it("normalizes a topic and persists the selected profile", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).includes("render-profiles")) {
        return new Response(JSON.stringify({ items: [profile], total: 1 }), { status: 200 });
      }
      expect(String(input)).toContain("/topics");
      expect(JSON.parse(String(init?.body))).toMatchObject({
        topic: "First topic",
        render_profile_id: "profile-1",
      });
      return new Response(JSON.stringify({ id: "batch-1" }), { status: 201 });
    });

    render(<Providers><CreateTopicForm /></Providers>);
    fireEvent.change(await screen.findByLabelText("Topic"), { target: { value: " First topic " } });
    fireEvent.change(screen.getByLabelText("Render profile"), { target: { value: "profile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create topic" }));

    await waitFor(() => expect(screen.getByText("Topic created successfully.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalled();
  });

  it("creates multiple independent topics when another topic is added", async () => {
    let requestUrl = "";
    let requestBody: Record<string, unknown> = {};
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).includes("render-profiles")) {
        return new Response(JSON.stringify({ items: [profile], total: 1 }), { status: 200 });
      }
      requestUrl = String(input);
      requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return new Response(JSON.stringify({ items: [{ id: "topic-1" }, { id: "topic-2" }], total: 2 }), { status: 201 });
    });

    render(<Providers><CreateTopicForm /></Providers>);
    await screen.findByRole("option", { name: "Elena Shelf" });
    fireEvent.click(screen.getByRole("button", { name: /Add another topic/ }));
    fireEvent.change(screen.getByLabelText("Topic 1"), { target: { value: "First topic" } });
    fireEvent.change(screen.getByLabelText("Topic 2"), { target: { value: "Second topic" } });
    fireEvent.change(screen.getByLabelText("Render profile"), { target: { value: "profile-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create 2 topics" }));

    await waitFor(() => expect(screen.getByText("2 topics created successfully.")).toBeVisible());
    expect(requestUrl).toContain("/topics/bulk");
    expect(requestBody).toMatchObject({
      topics: ["First topic", "Second topic"],
      render_profile_id: "profile-1",
    });
  });

  it("does not offer profiles without an assigned voice", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      items: [{ ...profile, voice_profile_id: null }],
      total: 1,
    }), { status: 200, headers: { "content-type": "application/json" } }));

    render(<Providers><CreateTopicForm /></Providers>);

    expect(await screen.findByText("Connect a voice to a render profile before creating a topic.")).toBeVisible();
    expect(screen.queryByRole("option", { name: "Elena Shelf" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create topic" })).toBeDisabled();
  });
});
