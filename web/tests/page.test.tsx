import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { Providers } from "../app/providers";
import {
  failedJobRetryKind,
  jobFailureMessage,
  RecentJobs,
  renderProgressLabel,
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
  });

  it("labels polling-only render progress as indeterminate", () => {
    expect(renderProgressLabel({ status: "rendering", progress: 1 })).toBe(
      "Progress unavailable (polling)",
    );
    expect(renderProgressLabel({ status: "completed", progress: 100 })).toBe("100%");
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

  it("shows job details and downloadable results in a collapsed job card", async () => {
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
          created_at: "2026-08-10T00:00:00Z",
          updated_at: "2026-08-10T00:01:00Z",
        }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    });

    const { container } = render(<Providers><RecentJobs contentGenerationReady detailed /></Providers>);

    expect(await screen.findByText("A useful reminder")).toBeInTheDocument();
    const card = container.querySelector("details.job-card");
    expect(card).not.toHaveAttribute("open");
    expect(screen.getByText("This is the generated speech.")).toBeInTheDocument();
    expect(screen.getByText(/Instagram title/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download finished.mp4" })).toHaveAttribute(
      "href",
      "/api/v1/assets/asset-1/download",
    );
  });
});
