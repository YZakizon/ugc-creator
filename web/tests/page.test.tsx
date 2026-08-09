import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { Providers } from "../app/providers";
import {
  failedJobRetryKind,
  jobFailureMessage,
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
});
