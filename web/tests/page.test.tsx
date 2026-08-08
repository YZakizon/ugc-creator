import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { Providers } from "../app/providers";

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
});
