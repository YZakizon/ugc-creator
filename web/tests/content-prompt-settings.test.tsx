import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "../app/providers";
import { ContentPromptSettings } from "../components/content-prompt-settings";

const defaultSettings = {
  provider: "openai",
  prompt_template: "Default {{TARGET_DURATION_SECONDS}} prompt.",
  prompt_version: "ugc-v1",
  default_prompt_template: "Default {{TARGET_DURATION_SECONDS}} prompt.",
  supported_placeholders: ["TARGET_DURATION_SECONDS"],
};

describe("content prompt settings", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("inserts the duration variable at the cursor and saves the prompt", async () => {
    let submitted: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "PUT") {
        submitted = JSON.parse(String(init.body));
        return new Response(JSON.stringify({
          ...defaultSettings,
          prompt_template: submitted?.prompt_template,
          prompt_version: "custom-saved",
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify(defaultSettings), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });

    render(<Providers><ContentPromptSettings /></Providers>);

    const textarea = await screen.findByLabelText(
      "Prompt template",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Start end" } });
    textarea.setSelectionRange(6, 6);
    fireEvent.click(screen.getByRole("button", { name: "{{TARGET_DURATION_SECONDS}}" }));
    expect(textarea).toHaveValue("Start {{TARGET_DURATION_SECONDS}}end");

    fireEvent.click(screen.getByRole("button", { name: "Save prompt" }));

    await waitFor(() => expect(submitted).toEqual({
      prompt_template: "Start {{TARGET_DURATION_SECONDS}}end",
    }));
    expect(await screen.findByText("OpenAI content prompt saved.")).toBeInTheDocument();
  });

  it("restores and persists the application default", async () => {
    let submitted: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "PUT") {
        submitted = JSON.parse(String(init.body));
        return new Response(JSON.stringify(defaultSettings), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({
        ...defaultSettings,
        prompt_template: "A custom prompt.",
        prompt_version: "custom-old",
      }), { status: 200, headers: { "content-type": "application/json" } });
    });

    render(<Providers><ContentPromptSettings /></Providers>);
    await screen.findByDisplayValue("A custom prompt.");
    fireEvent.click(screen.getByRole("button", { name: "Restore default" }));

    await waitFor(() => expect(submitted).toEqual({
      prompt_template: defaultSettings.default_prompt_template,
    }));
  });
});
