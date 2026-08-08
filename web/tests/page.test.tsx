import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { Providers } from "../app/providers";
import { failedJobRetryKind, renderProgressLabel } from "../components/dashboard-live-data";

describe("home page", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the connected API state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    render(<Providers>{await HomePage()}</Providers>);

    expect(screen.getByRole("status")).toHaveTextContent(
      "API connected",
    );
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
});
