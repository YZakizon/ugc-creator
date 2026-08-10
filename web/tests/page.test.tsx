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
  TopicHistory,
} from "../components/dashboard-live-data";
import type { Job } from "../lib/api";

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
    expect(
      jobFailureMessage({ status: "ready_to_render", error_message: "Provider unavailable" }),
    ).toContain("previous audio is still available");
  });

  it("generates more numbered content and confirms content and topic deletion", async () => {
    const content = (id: string, contentNumber: number): Job => ({
      id,
      batch_id: "topic-1",
      topic: "Burnout is not laziness",
      content_number: contentNumber,
      status: contentNumber === 1 ? "completed" : "queued",
      render_profile_id: "profile-1",
      voice_profile_id: "voice-1",
      workflow_template_id: "workflow-1",
      target_duration_seconds: 30,
      error_message: null,
      speech_script: contentNumber === 1 ? "A finished script." : null,
      hook: null,
      instagram_metadata: null,
      tiktok_metadata: null,
      llm_provider: contentNumber === 1 ? "openai" : null,
      llm_model: contentNumber === 1 ? "gpt-test" : null,
      prompt_version: contentNumber === 1 ? "ugc-v1" : null,
      tts_provider: null,
      tts_voice_id: null,
      tts_model: null,
      tts_provider_request_id: null,
      audio_asset: null,
      audio_assets: [],
      created_at: `2026-08-10T00:0${contentNumber}:00Z`,
      updated_at: `2026-08-10T00:0${contentNumber}:00Z`,
    });
    let contents = [content("content-1", 1)];
    let topicExists = true;
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      requests.push(`${method} ${url}`);
      if (url.endsWith("/topics/topic-1/contents") && method === "POST") {
        const next = content("content-2", 2);
        contents = [...contents, next];
        return new Response(JSON.stringify(next), { status: 202, headers: { "content-type": "application/json" } });
      }
      if (url.includes("/topics/topic-1/contents?") && method === "GET") {
        return new Response(JSON.stringify({ items: contents, total: contents.length, limit: 20, offset: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.endsWith("/contents/content-1") && method === "DELETE") {
        contents = contents.filter((item) => item.id !== "content-1");
        return new Response(null, { status: 204 });
      }
      if (url.endsWith("/topics/topic-1") && method === "DELETE") {
        topicExists = false;
        return new Response(null, { status: 204 });
      }
      if (url.includes("render-attempts") || url.includes("render-nodes") || url.includes("render-profiles") || url.includes("voice-profiles") || url.includes("workflow-templates")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("/topics")) {
        return new Response(JSON.stringify({
          items: topicExists ? [{
            id: "topic-1",
            name: "Burnout is not laziness",
            status: "processing",
            default_render_profile_id: "profile-1",
            target_duration_seconds: 30,
            auto_fit_duration: true,
            content_count: contents.length,
            created_at: "2026-08-10T00:00:00Z",
            updated_at: "2026-08-10T00:00:00Z",
            contents,
          }] : [],
          total: topicExists ? 1 : 0,
          limit: 20,
          offset: 0,
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });

    const { container } = render(<Providers><TopicHistory contentGenerationReady speechGenerationReady /></Providers>);
    await screen.findAllByText("Burnout is not laziness");
    fireEvent.click(container.querySelector(".topic-history-card > summary")!);
    fireEvent.click(within(container).getByRole("button", { name: /Generate more content/ }));
    await waitFor(() => expect(within(container).getAllByText("Content 2").length).toBeGreaterThan(0));

    const contentOne = Array.from(container.querySelectorAll("details.job-card")).find((card) => card.textContent?.includes("Content 1"))!;
    fireEvent.click(contentOne.querySelector("summary")!);
    fireEvent.click(within(contentOne as HTMLElement).getByRole("button", { name: "Delete content content-1" }));
    fireEvent.click(within(within(container).getByRole("dialog")).getByRole("button", { name: "Delete content" }));
    await waitFor(() => expect(within(container).queryByText("Content 1")).not.toBeInTheDocument());

    fireEvent.click(within(container).getByRole("button", { name: "Delete topic Burnout is not laziness" }));
    fireEvent.click(within(within(container).getByRole("dialog")).getByRole("button", { name: "Delete topic" }));
    await waitFor(() => expect(within(container).getByText("No topics yet")).toBeVisible());
    expect(requests).toContain("POST /api/v1/topics/topic-1/contents");
    expect(requests).toContain("DELETE /api/v1/contents/content-1");
    expect(requests).toContain("DELETE /api/v1/topics/topic-1");
  });

  it("paginates topic history beyond the first page", async () => {
    const requestedOffsets: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/topics?")) {
        const offset = new URL(url, "http://testserver").searchParams.get("offset") ?? "0";
        requestedOffsets.push(offset);
        return new Response(JSON.stringify({
          items: [{
            id: `topic-${offset}`,
            name: offset === "0" ? "Newest topic" : "Older topic",
            status: "draft",
            default_render_profile_id: null,
            target_duration_seconds: 30,
            auto_fit_duration: true,
            content_count: 0,
            created_at: "2026-08-10T00:00:00Z",
            updated_at: "2026-08-10T00:00:00Z",
            contents: [],
          }],
          total: 21,
          limit: 20,
          offset: Number(offset),
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("render-attempts") || url.includes("render-nodes") || url.includes("render-profiles") || url.includes("voice-profiles") || url.includes("workflow-templates")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<Providers><TopicHistory contentGenerationReady speechGenerationReady /></Providers>);
    await screen.findByText("Newest topic");
    expect(screen.getByText("Topics 1–1 of 21")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await screen.findByText("Older topic");
    expect(screen.getByText("Topics 21–21 of 21")).toBeVisible();
    expect(requestedOffsets).toContain("20");
  });

  it("allows deleting the only visible content on a later page", async () => {
    const makeContent = (number: number): Job => ({
      id: `content-${number}`,
      batch_id: "topic-1",
      topic: "Long-running topic",
      content_number: number,
      status: "completed",
      render_profile_id: null,
      voice_profile_id: null,
      workflow_template_id: null,
      target_duration_seconds: 30,
      error_message: null,
      speech_script: `Script ${number}`,
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
      audio_assets: [],
      created_at: "2026-08-10T00:00:00Z",
      updated_at: "2026-08-10T00:00:00Z",
    });
    let deleted = false;
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      requests.push(`${method} ${url}`);
      if (url.includes("/topics/topic-1/contents?") && method === "GET") {
        const offset = new URL(url, "http://testserver").searchParams.get("offset");
        const items = offset === "20" && !deleted ? [makeContent(21)] : offset === "0" ? [makeContent(1)] : [];
        return new Response(JSON.stringify({ items, total: deleted ? 20 : 21, limit: 20, offset: Number(offset) }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.endsWith("/contents/content-21") && method === "DELETE") {
        deleted = true;
        return new Response(null, { status: 204 });
      }
      if (url.includes("/topics?")) {
        return new Response(JSON.stringify({
          items: [{
            id: "topic-1",
            name: "Long-running topic",
            status: "completed",
            default_render_profile_id: null,
            target_duration_seconds: 30,
            auto_fit_duration: true,
            content_count: deleted ? 20 : 21,
            created_at: "2026-08-10T00:00:00Z",
            updated_at: "2026-08-10T00:00:00Z",
          }],
          total: 1,
          limit: 20,
          offset: 0,
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("render-attempts") || url.includes("render-nodes") || url.includes("render-profiles") || url.includes("voice-profiles") || url.includes("workflow-templates")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    });

    const { container } = render(<Providers><TopicHistory contentGenerationReady speechGenerationReady /></Providers>);
    await screen.findByText("Long-running topic");
    fireEvent.click(container.querySelector(".topic-history-card > summary")!);
    await screen.findAllByText("Content 1");
    fireEvent.click(screen.getByRole("button", { name: "Next content" }));
    await screen.findAllByText("Content 21");

    const contentCard = Array.from(container.querySelectorAll("details.job-card")).find((card) => card.textContent?.includes("Content 21"))!;
    fireEvent.click(contentCard.querySelector("summary")!);
    const deleteButton = within(contentCard as HTMLElement).getByRole("button", { name: "Delete content content-21" });
    expect(deleteButton).toBeEnabled();
    fireEvent.click(deleteButton);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete content" }));

    await waitFor(() => expect(requests).toContain("DELETE /api/v1/contents/content-21"));
  });

  it("returns to the prior topic page when a later page becomes empty", async () => {
    let firstPageRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/topics?")) {
        const offset = new URL(url, "http://testserver").searchParams.get("offset") ?? "0";
        if (offset === "0") firstPageRequests += 1;
        return new Response(JSON.stringify({
          items: offset === "0" ? [{
            id: "topic-1",
            name: "Remaining topic",
            status: "draft",
            default_render_profile_id: null,
            target_duration_seconds: 30,
            auto_fit_duration: true,
            content_count: 0,
            created_at: "2026-08-10T00:00:00Z",
            updated_at: "2026-08-10T00:00:00Z",
            contents: [],
          }] : [],
          total: offset === "0" ? 21 : 20,
          limit: 20,
          offset: Number(offset),
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("render-attempts") || url.includes("render-nodes") || url.includes("render-profiles") || url.includes("voice-profiles") || url.includes("workflow-templates")) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    const { container } = render(<Providers><TopicHistory contentGenerationReady speechGenerationReady /></Providers>);
    await within(container).findByText("Remaining topic");
    fireEvent.click(within(container).getByRole("button", { name: "Next" }));

    await waitFor(() => expect(firstPageRequests).toBeGreaterThan(1));
    expect(within(container).getByText("Remaining topic")).toBeVisible();
    expect(within(container).queryByText("No topics yet")).not.toBeInTheDocument();
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
          content_number: 1,
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
    const requests: Array<{ url: string; body: string }> = [];
    let currentJob: Job = {
      id: "job-1",
      batch_id: "batch-1",
      topic: "A useful reminder",
      content_number: 1,
      status: "completed",
      render_profile_id: "profile-1",
      voice_profile_id: "voice-profile-1",
      workflow_template_id: "workflow-1",
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
        generation_metadata: null,
        download_url: "/api/v1/assets/audio-1/download",
        created_at: "2026-08-10T00:00:30Z",
      },
      audio_assets: [],
      created_at: "2026-08-10T00:00:00Z",
      updated_at: "2026-08-10T00:01:00Z",
    };
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/api/v1/jobs/job-1/")) {
        requests.push({ url, body: String(init?.body ?? "") });
        if (url.endsWith("/voice-profile")) {
          currentJob = { ...currentJob, status: "content_ready", voice_profile_id: "voice-profile-2", audio_asset: null, updated_at: "2026-08-10T00:02:00Z" };
        } else if (url.endsWith("/render-profile")) {
          currentJob = { ...currentJob, status: "ready_to_render", render_profile_id: "profile-2", voice_profile_id: "voice-profile-2", workflow_template_id: "workflow-2", updated_at: "2026-08-10T00:03:00Z" };
        } else if (url.endsWith("/workflow-template")) {
          currentJob = { ...currentJob, status: "ready_to_render", workflow_template_id: "workflow-1", updated_at: "2026-08-10T00:04:00Z" };
        } else if (url.endsWith("/audio")) {
          currentJob = { ...currentJob, status: "ready_to_render", audio_asset: { id: "audio-2", job_id: "job-1", kind: "audio", filename: "replacement.mp3", content_type: "audio/mpeg", size_bytes: 17, generation_metadata: null, download_url: "/api/v1/assets/audio-2/download", created_at: "2026-08-10T00:05:00Z" }, updated_at: "2026-08-10T00:05:00Z" };
        }
        return new Response(JSON.stringify(currentJob), { status: 200, headers: { "content-type": "application/json" } });
      }
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
        return new Response(JSON.stringify({ items: [{ id: "profile-1", name: "Elena LTX", voice_profile_id: "voice-profile-1", workflow_template_id: "workflow-1", is_active: true }, { id: "profile-2", name: "Elena Studio", voice_profile_id: "voice-profile-2", workflow_template_id: "workflow-2", is_active: true }], total: 2 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("workflow-templates")) {
        return new Response(JSON.stringify({ items: [{ id: "workflow-1", name: "LTX workflow", renderer_provider: "comfyui" }, { id: "workflow-2", name: "LTX workflow 2", renderer_provider: "comfyui" }], total: 2 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url.includes("voice-profiles")) {
        const voiceDefaults = { provider: "elevenlabs", provider_voice_id: "voice-id", provider_model: "eleven_multilingual_v2", speed: 1, stability: 0.5, similarity: 0.75, style_exaggeration: 0.5, extra_settings: { voice_name: "Elena" }, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T00:00:00Z" };
        return new Response(JSON.stringify({ items: [{ ...voiceDefaults, id: "voice-profile-1", name: "Hope voice" }, { ...voiceDefaults, id: "voice-profile-2", name: "Elena voice" }], total: 2 }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({
        in_progress: 0,
        ready_to_render: 0,
        completed_videos: 1,
        render_profiles: 2,
        recent_jobs: [currentJob],
      }), { status: 200, headers: { "content-type": "application/json" } });
    });

    const { container } = render(<Providers><RecentJobs contentGenerationReady speechGenerationReady detailed /></Providers>);

    expect((await screen.findAllByText("Content 1")).length).toBeGreaterThan(0);
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
    expect(jobCard.getByRole("button", { name: "Show Topic ID" })).toBeInTheDocument();
    expect(jobCard.getByRole("button", { name: "Show Render profile ID" })).toBeInTheDocument();
    fireEvent.click(jobCard.getByRole("button", { name: "Show Content ID" }));
    expect(jobCard.getByText("job-1")).toBeVisible();
    fireEvent.click(jobCard.getByRole("button", { name: "Copy Content ID" }));
    expect(writeText).toHaveBeenCalledWith("job-1");
    expect(jobCard.getByRole("link", { name: "Download generated speech" })).toHaveAttribute(
      "href",
      "/api/v1/assets/audio-1/download",
    );
    expect(jobCard.getByRole("link", { name: "Download finished.mp4", hidden: true })).toHaveAttribute(
      "href",
      "/api/v1/assets/asset-1/download",
    );
    expect(jobCard.getByRole("combobox", { name: "Voice profile", hidden: true })).toHaveValue("voice-profile-1");
    expect(jobCard.getByRole("combobox", { name: "Voice profile", hidden: true })).toBeEnabled();
    expect(jobCard.getByRole("link", { name: "Open voice profile details", hidden: true })).toHaveAttribute("href", "/voice-profiles#voice-profile-voice-profile-1");
    fireEvent.click(jobCard.getByRole("button", { name: "Generate audio" }));
    await waitFor(() => expect(requests.some((request) => request.url.endsWith("/generate-tts"))).toBe(true));
    fireEvent.change(jobCard.getByRole("combobox", { name: "Voice profile", hidden: true }), { target: { value: "voice-profile-2" } });
    fireEvent.click(jobCard.getByRole("button", { name: "Save voice profile", hidden: true }));
    await waitFor(() => expect(requests.some((request) => request.url.endsWith("/voice-profile") && request.body === JSON.stringify({ voice_profile_id: "voice-profile-2" }))).toBe(true));
    fireEvent.click(jobCard.getByRole("tab", { name: "Render ComfyUI" }));
    expect(jobCard.getByRole("combobox", { name: "Render profile" })).toBeEnabled();
    fireEvent.change(jobCard.getByRole("combobox", { name: "Render profile" }), { target: { value: "profile-2" } });
    fireEvent.click(jobCard.getByRole("button", { name: "Save render profile" }));
    await waitFor(() => expect(requests.some((request) => request.url.endsWith("/render-profile") && request.body === JSON.stringify({ render_profile_id: "profile-2" }))).toBe(true));
    expect(jobCard.getByRole("combobox", { name: "Workflow" })).toHaveValue("workflow-2");
    expect(jobCard.getByRole("combobox", { name: "Workflow" })).toBeEnabled();
    fireEvent.change(jobCard.getByRole("combobox", { name: "Workflow" }), { target: { value: "workflow-1" } });
    fireEvent.click(jobCard.getByRole("button", { name: "Save workflow" }));
    await waitFor(() => expect(requests.some((request) => request.url.endsWith("/workflow-template") && request.body === JSON.stringify({ workflow_template_id: "workflow-1" }))).toBe(true));
    expect(jobCard.getByRole("link", { name: "Open workflow details" })).toHaveAttribute("href", "/workflows#workflow-workflow-1");
    const upload = jobCard.getByLabelText("Upload different audio");
    expect(upload).toBeEnabled();
    fireEvent.change(upload, { target: { files: [new File(["replacement audio"], "replacement.mp3", { type: "audio/mpeg" })] } });
    await waitFor(() => expect(requests.some((request) => request.url.endsWith("/audio") && request.body.includes('"filename":"replacement.mp3"'))).toBe(true));
    expect(await within(card!.querySelector(".job-render-audio") as HTMLElement).findByText("replacement.mp3")).toBeVisible();
    expect(jobCard.queryByRole("link", { name: "Download render audio" })).not.toBeInTheDocument();
    expect(jobCard.queryByRole("button", { name: "Show Render attempt ID" })).not.toBeInTheDocument();
    fireEvent.click(jobCard.getByRole("button", { name: "Show ComfyUI Job ID" }));
    expect(jobCard.getByText("prompt-1")).toBeVisible();
    fireEvent.click(jobCard.getByRole("button", { name: "Preview finished.mp4" }));
    expect(card!.querySelector("video")).toHaveAttribute("src", "/api/v1/assets/asset-1/download?inline=true");
    expect(jobCard.getByRole("button", { name: "Delete finished.mp4" })).toBeInTheDocument();
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
      const job = { id: "job-1", batch_id: "batch-1", topic: "Change scene", content_number: 1, status: "content_ready", render_profile_id: url.includes("render-profile") ? "profile-2" : "profile-1", target_duration_seconds: 30, error_message: null, speech_script: "Ready script.", hook: "Hook", instagram_metadata: null, tiktok_metadata: null, llm_provider: "openai", llm_model: "gpt-test", prompt_version: "ugc-v1", tts_provider: null, tts_voice_id: null, tts_model: null, tts_provider_request_id: null, audio_asset: null, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T00:01:00Z" };
      if (url.includes("/render-profile")) {
        updateBody = String(init?.body);
        return new Response(JSON.stringify(job), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ in_progress: 0, ready_to_render: 0, completed_videos: 0, render_profiles: 2, recent_jobs: [job] }), { status: 200, headers: { "content-type": "application/json" } });
    });

    const { container } = render(<Providers><RecentJobs contentGenerationReady speechGenerationReady detailed /></Providers>);
    await waitFor(() => expect(container.querySelector("details.job-card")).not.toBeNull());
    const card = container.querySelector("details.job-card")!;
    fireEvent.click(card.querySelector("summary")!);
    const jobCard = within(card as HTMLElement);
    fireEvent.click(jobCard.getByRole("tab", { name: "Render ComfyUI" }));
    fireEvent.change(await jobCard.findByLabelText("Render profile"), { target: { value: "profile-2" } });
    fireEvent.click(jobCard.getByRole("button", { name: "Save render profile" }));

    await waitFor(() => expect(updateBody).toBe(JSON.stringify({ render_profile_id: "profile-2" })));
  });
});
