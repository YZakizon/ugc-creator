import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "../app/providers";
import { RenderProfileSetup } from "../components/render-profile-setup";

describe("render profile setup", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("expands profile data into an inline editor without an edit icon", async () => {
    let updatePayload: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "PATCH") {
        updatePayload = JSON.parse(String(init.body));
        return new Response(JSON.stringify({
          id: "profile-1",
          name: "Elena profile",
          character_id: "character-1",
          voice_profile_id: null,
          renderer_provider: "comfyui",
          workflow_template_id: "workflow-1",
          is_active: true,
          created_at: "2026-08-07T12:00:00Z",
          updated_at: "2026-08-07T12:01:00Z",
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("workflow-templates")) {
        return new Response(JSON.stringify({
          items: [{
            id: "workflow-1",
            name: "LTX workflow",
            description: null,
            renderer_provider: "comfyui",
            workflow_json: {},
            metadata_json: {},
            version: 1,
            checksum: "checksum",
            bindings: [],
            created_at: "2026-08-07T12:00:00Z",
            updated_at: "2026-08-07T12:00:00Z",
          }],
          total: 1,
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("voice-profiles")) {
        return new Response(JSON.stringify({
          items: [{ id: "voice-1", name: "Elena voice", provider: "elevenlabs", provider_voice_id: "elevenlabs-elena-123", provider_model: null, speed: 1, stability: null, similarity: null, style_exaggeration: null, extra_settings: { voice_name: "Elena" }, created_at: "2026-08-07T12:00:00Z", updated_at: "2026-08-07T12:00:00Z" }],
          total: 1,
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("characters")) {
        return new Response(JSON.stringify({
          items: [{ id: "character-1", name: "Elena", slug: "elena" }],
          total: 1,
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({
        items: [{
          id: "profile-1",
          name: "Elena profile",
          character_id: "character-1",
          voice_profile_id: "voice-1",
          renderer_provider: "comfyui",
          workflow_template_id: "workflow-1",
          is_active: true,
          created_at: "2026-08-07T12:00:00Z",
          updated_at: "2026-08-07T12:00:00Z",
        }],
        total: 1,
      }), { status: 200, headers: { "content-type": "application/json" } });
    });

    render(<Providers><RenderProfileSetup /></Providers>);

    const profileToggle = await screen.findByRole("button", { name: "Show Elena profile details" });
    expect(screen.queryByRole("button", { name: /Edit Elena profile/i })).not.toBeInTheDocument();

    fireEvent.click(profileToggle);

    const saveButton = screen.getByRole("button", { name: "Save changes" });
    const editForm = saveButton.closest("form");
    const profileDetails = document.getElementById("profile-details-profile-1");
    expect(editForm).not.toBeNull();
    expect(profileDetails).not.toBeNull();
    expect(within(editForm as HTMLFormElement).getByLabelText("Profile name")).toHaveValue("Elena profile");
    expect(within(profileDetails as HTMLElement).getByLabelText("Character name")).toHaveValue("Elena");
    expect(within(profileDetails as HTMLElement).getByLabelText("Voice profile")).toHaveValue("voice-1");
    expect(within(profileDetails as HTMLElement).getByLabelText("Workflow template")).toHaveValue("workflow-1");

    fireEvent.change(within(profileDetails as HTMLElement).getByLabelText("Voice profile"), { target: { value: "" } });
    expect(within(profileDetails as HTMLElement).getByRole("option", { name: "Not assigned" })).toBeVisible();
    fireEvent.click(saveButton);
    await screen.findByText("Profile updated successfully.");
    expect(updatePayload).toMatchObject({ voice_profile_id: null });
  });

  it("opens the create tab from the hash and blocks creation when workflows fail to load", async () => {
    window.history.replaceState(null, "", "/profiles#new-profile");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("workflow-templates")) {
        return new Response(JSON.stringify({ detail: "workflow service unavailable" }), { status: 503, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
    });

    render(<Providers><RenderProfileSetup /></Providers>);

    expect(screen.getByRole("tab", { name: "Create profile" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Workflow template")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create profile" })).toBeDisabled();
  });
});
