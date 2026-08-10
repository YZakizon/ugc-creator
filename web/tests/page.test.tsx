import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { Providers } from "../app/providers";
import {
  failedJobRetryKind,
  jobFailureMessage,
  RecentJobs,
  renderProgressLabel,
  speechScriptLines,
} from "../components/dashboard-live-data";

describe("home page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the connected API state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        status: "ok",
        ready: true,
        checks: {
          openai: { configured: true, message: "OpenAI is configured." },
          elevenlabs: { configured: true, message: "ElevenLabs is configured." },
        },
        warnings: [],
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    render(<Providers>{await HomePage()}</Providers>);

    expect(screen.getByRole("status")).toHaveTextContent(
      "API connected",
    );
  });

  it("warns before generation when OpenAI is not configured", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        status: "ok",
        ready: false,
        checks: {
          openai: { configured: false, message: "OpenAI setup required." },
          elevenlabs: { configured: true, message: "ElevenLabs is configured." },
        },
        warnings: ["OpenAI is not configured. Set OPENAI_API_KEY in the root .env file and restart Docker before generating content."],
      }), { status: 200, headers: { "content-type": "application/json" } }),
    );

    render(<Providers>{await HomePage()}</Providers>);

    expect(screen.getByRole("alert")).toHaveTextContent("Setup required before generation");
    expect(screen.getByRole("alert")).toHaveTextContent("OPENAI_API_KEY");
    expect(screen.getByText("Setup required", { selector: "b" })).toBeInTheDocument();
  });

  it("retries the failed pipeline stage instead of overwriting valid content", () => {
    expect(
      failedJobRetryKind(
        { status: "failed", speech_script: "Existing valid speech" },
        { status: "failed" },
      ),
    ).toBe("render");
    expect(
      failedJobRetryKind(
        { status: "failed", speech_script: null },
        undefined,
      ),
    ).toBe("content");
    expect(
      failedJobRetryKind(
        { status: "failed", speech_script: "Content is ready" },
        undefined,
      ),
    ).toBe("tts");
  });

  it("labels polling-only render progress as indeterminate", () => {
    expect(renderProgressLabel({ status: "rendering", progress: 1 })).toBe(
      "Progress unavailable (polling)",
    );
    expect(renderProgressLabel({ status: "completed", progress: 100 })).toBe("100%");
  });

  it("shows every speech sentence on its own reading line", () => {
    expect(speechScriptLines("First sentence. Second sentence!\nThird sentence?”")).toEqual([
      "First sentence.",
      "Second sentence!",
      "Third sentence?”",
    ]);
  });

  it("shows the persisted reason when a job fails", () => {
    expect(
      jobFailureMessage({
        status: "failed",
        error_message: "OpenAI is not configured on the server",
      }),
    ).toBe("OpenAI is not configured on the server");
    expect(
      jobFailureMessage({ status: "failed", error_message: null }),
    ).toContain("failed without a detailed error");
    expect(
      jobFailureMessage({ status: "content_ready", error_message: "stale" }),
    ).toBeNull();
  });

  it("offers only speech retry when generated content is still valid", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("render-attempts") || url.includes("render-nodes")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({
        in_progress: 0,
        ready_to_render: 0,
        completed_videos: 0,
        render_profiles: 1,
        recent_jobs: [{
          id: "job-tts-failed",
          batch_id: "batch-1",
          topic: "Keep the generated content",
          status: "failed",
          render_profile_id: "profile-1",
          target_duration_seconds: 30,
          error_message: "ElevenLabs was unavailable",
          speech_script: "Valid generated speech content.",
          hook: null,
          instagram_metadata: null,
          tiktok_metadata: null,
          llm_provider: "openai",
          llm_model: "gpt-test",
          prompt_version: "ugc-v1",
          tts_provider: null,
          tts_voice_id: null,
          tts_model: null,
          tts_provider_request_id: null,
          audio_asset: null,
          created_at: "2026-08-10T00:00:00Z",
          updated_at: "2026-08-10T00:01:00Z",
        }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    });

    render(<Providers><RecentJobs contentGenerationReady speechGenerationReady detailed /></Providers>);

    expect(await screen.findByRole("button", { name: "Retry speech" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate content" })).not.toBeInTheDocument();
  });

  it("shows job details and downloadable results in a collapsed job card", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("render-attempts")) {
        return new Response(JSON.stringify({ items: [{
          id: "attempt-1",
          job_id: "job-1",
          render_profile_id: "profile-1",
          render_node_id: "node-1",
          workflow_template_id: "workflow-1",
          provider: "comfyui",
          status: "completed",
          progress: 100,
          external_job_id: "prompt-1",
          error_message: null,
          created_at: "2026-08-10T00:00:00Z",
          updated_at: "2026-08-10T00:01:00Z",
          assets: [{
            id: "asset-1",
            job_id: "job-1",
            kind: "video",
            filename: "finished.mp4",
            content_type: "video/mp4",
            size_bytes: 1024,
            download_url: "/api/v1/assets/asset-1/download",
            created_at: "2026-08-10T00:01:00Z",
          }],
        }], total: 1 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("render-nodes")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("/api/v1/batches")) {
        return new Response(JSON.stringify({ items: [{ id: "batch-1", name: "August launch", jobs: [] }], total: 1, limit: 100, offset: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("render-profiles")) {
        return new Response(JSON.stringify({ items: [{ id: "profile-1", name: "Elena LTX", is_active: true }], total: 1 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("workflow-templates")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("voice-profiles")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({
        in_progress: 0,
        ready_to_render: 0,
        completed_videos: 1,
        render_profiles: 1,
        recent_jobs: [{
          id: "job-1",
          batch_id: "batch-1",
          topic: "A useful reminder",
          status: "completed",
          render_profile_id: "profile-1",
          target_duration_seconds: 30,
          error_message: null,
          speech_script: "This is the generated speech.",
          hook: "Start here.",
          instagram_metadata: { title: "Instagram title" },
          tiktok_metadata: { title: "TikTok title" },
          llm_provider: "openai",
          llm_model: "gpt-test",
          prompt_version: "ugc-v1",
          tts_provider: "elevenlabs",
          tts_voice_id: "voice-1",
          tts_model: "eleven_multilingual_v2",
          tts_provider_request_id: "tts-request-1",
          audio_asset: {
            id: "audio-1",
            job_id: "job-1",
            kind: "audio",
            filename: "speech.mp3",
            content_type: "audio/mpeg",
            size_bytes: 512,
            download_url: "/api/v1/assets/audio-1/download",
            created_at: "2026-08-10T00:00:30Z",
          },
          created_at: "2026-08-10T00:00:00Z",
          updated_at: "2026-08-10T00:01:00Z",
        }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    });

    const { container } = render(<Providers><RecentJobs contentGenerationReady speechGenerationReady detailed /></Providers>);

    expect((await screen.findAllByText("A useful reminder")).length).toBeGreaterThan(0);
    expect(await screen.findAllByText("August launch")).not.toHaveLength(0);
    expect(screen.getAllByText("Elena LTX")).not.toHaveLength(0);
    const card = container.querySelector("details.job-card");
    expect(card).not.toHaveAttribute("open");
    fireEvent.click(card!.querySelector("summary")!);
    expect(card).toHaveAttribute("open");
    const jobCard = within(card as HTMLElement);
    expect(screen.getByText("This is the generated speech.")).toBeInTheDocument();
    expect(jobCard.getByRole("tab", { name: "Hook + Speech Script" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(jobCard.getByRole("tab", { name: "Instagram" }));
    expect(jobCard.getByText(/Instagram title/)).toBeVisible();
    expect(jobCard.queryByText("Technical IDs")).not.toBeInTheDocument();
    expect(jobCard.queryByText("job-1")).not.toBeInTheDocument();
    expect(jobCard.getByRole("button", { name: "Show Batch ID" })).toBeInTheDocument();
    expect(jobCard.getByRole("button", { name: "Show Render profile ID" })).toBeInTheDocument();
    fireEvent.click(jobCard.getByRole("button", { name: "Show Job ID" }));
    expect(jobCard.getByText("job-1")).toBeVisible();
    fireEvent.click(jobCard.getByRole("button", { name: "Copy Job ID" }));
    expect(writeText).toHaveBeenCalledWith("job-1");
    expect(jobCard.getByRole("link", { name: "Download generated speech" })).toHaveAttribute(
      "href",
      "/api/v1/assets/audio-1/download",
    );
    expect(jobCard.getByRole("link", { name: "Download finished.mp4", hidden: true })).toHaveAttribute(
      "href",
      "/api/v1/assets/asset-1/download",
    );
  });

  it("changes a job render profile from the Render ComfyUI tab", async () => {
    let updateBody: string | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("render-attempts") || url.includes("render-nodes")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("/api/v1/batches")) {
        return new Response(JSON.stringify({ items: [{ id: "batch-1", name: "Launch batch", jobs: [] }], total: 1, limit: 100, offset: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("render-profiles")) {
        return new Response(JSON.stringify({ items: [{ id: "profile-1", name: "Shelf", is_active: true }, { id: "profile-2", name: "Studio", is_active: true }], total: 2 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("workflow-templates")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("voice-profiles")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      const job = { id: "job-1", batch_id: "batch-1", topic: "Change scene", status: "content_ready", render_profile_id: url.includes("render-profile") ? "profile-2" : "profile-1", target_duration_seconds: 30, error_message: null, speech_script: "Ready script.", hook: "Hook", instagram_metadata: null, tiktok_metadata: null, llm_provider: "openai", llm_model: "gpt-test", prompt_version: "ugc-v1", tts_provider: null, tts_voice_id: null, tts_model: null, tts_provider_request_id: null, audio_asset: null, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T00:01:00Z" };
      if (url.includes("/render-profile")) {
        updateBody = String(init?.body);
        return new Response(JSON.stringify(job), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ in_progress: 0, ready_to_render: 0, completed_videos: 0, render_profiles: 2, recent_jobs: [job] }), { status: 200, headers: { "content-type": "application/json" } });
    });

    const { container } = render(<Providers><RecentJobs contentGenerationReady speechGenerationReady detailed /></Providers>);
    expect((await screen.findAllByText("Change scene")).length).toBeGreaterThan(0);
    const card = container.querySelector("details.job-card")!;
    fireEvent.click(card.querySelector("summary")!);
    const jobCard = within(card as HTMLElement);
    fireEvent.click(jobCard.getByRole("tab", { name: "Render ComfyUI" }));
    fireEvent.change(await jobCard.findByLabelText("Render profile"), { target: { value: "profile-2" } });
    fireEvent.click(jobCard.getByRole("button", { name: "Save render profile" }));

    await waitFor(() => expect(updateBody).toBe(JSON.stringify({ render_profile_id: "profile-2" })));
  });
});
