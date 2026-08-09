import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "../app/providers";
import { VoiceProfileSetup } from "../components/voice-profile-setup";

describe("voice profile setup", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("creates a reusable ElevenLabs voice with normalized settings", async () => {
    let submitted: Record<string, unknown> | null = null;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (!init?.method) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
      }
      const payload = JSON.parse(String(init.body));
      submitted = payload;
      return new Response(JSON.stringify({
        id: "voice-profile-1",
        ...payload,
        created_at: "2026-08-07T12:00:00Z",
        updated_at: "2026-08-07T12:00:00Z",
      }), { status: 201, headers: { "content-type": "application/json" } });
    });

    render(<Providers><VoiceProfileSetup /></Providers>);
    fireEvent.click(screen.getByRole("tab", { name: "Create voice profile" }));
    fireEvent.change(screen.getByLabelText("Voice profile name"), { target: { value: "Elena — Hope" } });
    fireEvent.change(screen.getByLabelText("Voice name"), { target: { value: "Hope" } });
    fireEvent.change(screen.getByLabelText("Voice ID"), { target: { value: "voice-123" } });
    expect(screen.getByRole("slider", { name: "Style Exaggeration" })).toHaveValue("50");
    fireEvent.input(screen.getByRole("slider", { name: "Speed" }), { target: { value: "1.1" } });
    fireEvent.input(screen.getByRole("slider", { name: "Stability" }), { target: { value: "55" } });
    fireEvent.input(screen.getByRole("slider", { name: "Similarity" }), { target: { value: "80" } });
    fireEvent.input(screen.getByRole("slider", { name: "Style Exaggeration" }), { target: { value: "15" } });
    fireEvent.click(screen.getByRole("button", { name: "Create voice profile" }));

    await waitFor(() => expect(screen.getByText("Voice profile created.")).toBeInTheDocument());
    expect(submitted).toMatchObject({
      name: "Elena — Hope",
      provider: "elevenlabs",
      provider_voice_id: "voice-123",
      speed: 1.1,
      stability: 0.55,
      similarity: 0.8,
      style_exaggeration: 0.15,
      extra_settings: { voice_name: "Hope" },
    });
    expect(fetchMock).toHaveBeenCalled();
  });

  it("links to each render profile blocking voice deletion", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "DELETE") {
        return new Response(JSON.stringify({
          detail: {
            code: "voice_profile_in_use",
            message: "Voice profile is in use by render profiles: Elena Shelf (ID: profile-123)",
            render_profiles: [{ id: "profile-123", name: "Elena Shelf" }],
            characters: [],
          },
        }), { status: 409, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({
        items: [{
          id: "voice-1",
          name: "Hope voice",
          provider: "elevenlabs",
          provider_voice_id: "voice-123",
          provider_model: "eleven_multilingual_v2",
          speed: 1,
          stability: 0.5,
          similarity: 0.75,
          style_exaggeration: 0,
          extra_settings: { voice_name: "Hope" },
          created_at: "2026-08-07T12:00:00Z",
          updated_at: "2026-08-07T12:00:00Z",
        }],
        total: 1,
      }), { status: 200, headers: { "content-type": "application/json" } });
    });

    render(<Providers><VoiceProfileSetup /></Providers>);
    fireEvent.click(await screen.findByRole("button", { name: "Delete Hope voice" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    const profileLink = await screen.findByRole("link", { name: "Open Elena Shelf · profile-123" });
    expect(profileLink).toHaveAttribute("href", "/profiles#profile-profile-123");
  });

  it("queues speech generation and exposes playback and download", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("tts-providers/elevenlabs/usage")) {
        return new Response(JSON.stringify({ provider: "elevenlabs", configured: true, used_units: 125, limit_units: 10000, remaining_units: 9875, resets_at_unix: null, unit: "characters" }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("tts-providers/elevenlabs/voices")) {
        return new Response(JSON.stringify({ items: [{ voice_id: "voice-catalog-1", name: "Catalog Hope", category: "generated", description: "Warm and clear", preview_url: "https://example.test/hope.mp3" }, { voice_id: "voice-catalog-2", name: "Catalog Joy", category: "cloned", description: "Bright and lively", preview_url: "https://example.test/joy.mp3" }], total: 2 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (init?.method === "POST" && url.includes("/previews")) {
        return new Response(JSON.stringify({
          id: "preview-1", voice_profile_id: "voice-1", text: "Preview me", status: "queued", provider: "elevenlabs", provider_request_id: null, content_type: null, filename: null, error_message: null, download_url: null, created_at: "2026-08-07T12:00:00Z", updated_at: "2026-08-07T12:00:00Z",
        }), { status: 202, headers: { "content-type": "application/json" } });
      }
      if (url.includes("voice-previews/preview-1")) {
        return new Response(JSON.stringify({
          id: "preview-1", voice_profile_id: "voice-1", text: "Preview me", status: "completed", provider: "elevenlabs", provider_request_id: "request-1", generated_usage_units: 10, account_used_units: 125, account_limit_units: 10000, account_remaining_units: 9875, usage_resets_at_unix: null, usage_unit: "characters", content_type: "audio/mpeg", filename: "preview.mp3", error_message: null, download_url: "/api/v1/voice-previews/preview-1/audio", created_at: "2026-08-07T12:00:00Z", updated_at: "2026-08-07T12:00:01Z",
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("voice-profiles/voice-1/previews")) {
        return new Response(JSON.stringify({ items: [{
          id: "preview-active", voice_profile_id: "voice-1", text: "Still generating", status: "generating", provider: "elevenlabs", provider_request_id: null, generated_usage_units: null, account_used_units: null, account_limit_units: null, account_remaining_units: null, usage_resets_at_unix: null, usage_unit: null, content_type: null, filename: null, error_message: null, download_url: null, created_at: "2026-08-07T12:01:00Z", updated_at: "2026-08-07T12:01:00Z",
        }], total: 1 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({
        items: [{ id: "voice-1", name: "Hope voice", provider: "elevenlabs", provider_voice_id: "voice-123", provider_model: "eleven_multilingual_v2", speed: 1, stability: 0.5, similarity: 0.75, style_exaggeration: 0.5, extra_settings: { voice_name: "Hope" }, created_at: "2026-08-07T12:00:00Z", updated_at: "2026-08-07T12:00:00Z" }], total: 1,
      }), { status: 200, headers: { "content-type": "application/json" } });
    });

    render(<Providers><VoiceProfileSetup /></Providers>);
    expect(await screen.findByText("9,875")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Show Hope voice details" }));
    expect(screen.getByRole("tab", { name: "Preview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Preview to generate speech" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Generated speech history" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Choose from ElevenLabs My Voices" }));
    expect(await screen.findByRole("dialog", { name: "ElevenLabs My Voices" })).toBeInTheDocument();
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Preview Catalog Hope" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview Catalog Joy" }));
    expect(play).toHaveBeenCalledTimes(2);
    expect(pause).toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { name: "Use voice" })[0]);
    expect(screen.getAllByLabelText("Voice name")[1]).toHaveValue("Catalog Hope");
    expect(screen.getAllByLabelText("Voice ID")[1]).toHaveValue("voice-catalog-1");
    const previewText = await screen.findByPlaceholderText("Enter text to generate speech…");
    const generateButton = screen.getByRole("button", { name: "Generate speech" });
    expect(previewText.compareDocumentPosition(generateButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.change(previewText, { target: { value: "Preview me" } });
    fireEvent.click(generateButton);

    const download = await screen.findByRole("link", { name: "Download audio" });
    expect(download).toHaveAttribute("href", "/api/v1/voice-previews/preview-1/audio");
    expect(download).toHaveTextContent("");
    expect(screen.getByText("10 characters")).toBeInTheDocument();
    expect(screen.getByText("9,875 of 10,000 characters")).toBeInTheDocument();
    expect(Array.from(document.querySelectorAll("audio")).some((audio) => audio.getAttribute("src") === "/api/v1/voice-previews/preview-1/audio")).toBe(true);
    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Generated speech history" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Preview to generate speech" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete generated speech" })).toBeDisabled();
  });
});
