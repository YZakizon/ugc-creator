import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "../app/providers";
import { WorkflowTemplateSetup, WorkflowWorkspace } from "../components/workflow-template-setup";

describe("workflow template setup", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.sessionStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("preserves custom semantic bindings while raw workflow JSON is edited", async () => {
    let submitted: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "PUT") {
        submitted = JSON.parse(String(init.body));
        return new Response(JSON.stringify({
          id: "workflow-1", logical_id: "workflow-1", name: "Custom workflow", description: null, renderer_provider: "comfyui", workflow_json: {}, metadata_json: {}, version: 2, checksum: "new-checksum", bindings: [], created_at: "2026-08-08T12:00:00Z", updated_at: "2026-08-08T12:00:00Z",
        }), { status: 201, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
    });
    window.sessionStorage.setItem("workflow-template-edit", JSON.stringify({
      id: "workflow-1",
      logical_id: "workflow-1",
      name: "Custom workflow",
      description: null,
      renderer_provider: "comfyui",
      workflow_json: {
        "27": { class_type: "KSampler", inputs: { seed: 42, steps: 20 } },
      },
      metadata_json: {
        default_workflow_media: {
          source_image: "workflow-media/8b60d3ba-d861-4922-9c71-7704cc7e12ed-saved-image.png",
          audio: "workflow-media/e1c13175-1657-4ff0-82aa-1b437eb06cf7-saved-audio.mp3",
        },
      },
      version: 1,
      checksum: "checksum",
      bindings: [{ id: "binding-1", semantic_key: "kling.camera_strength", node_id: "27", input_name: "seed", value_type: "integer", required: true }],
      created_at: "2026-08-07T12:00:00Z",
      updated_at: "2026-08-07T12:00:00Z",
    }));

    render(<Providers><WorkflowTemplateSetup /></Providers>);

    const workflowJson = await screen.findByLabelText("ComfyUI API workflow JSON");
    expect(screen.getByText("saved-image.png")).toBeInTheDocument();
    expect(screen.getByText("saved-audio.mp3")).toBeInTheDocument();
    expect(screen.queryByText("Semantic bindings")).not.toBeInTheDocument();
    fireEvent.change(workflowJson, {
      target: { value: JSON.stringify({ "27": { class_type: "KSampler", inputs: { seed: 99, steps: 25 } } }, null, 2) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Update workflow" }));

    await waitFor(() => expect(submitted).not.toBeNull());
    expect(submitted).toMatchObject({ bindings: [{ semantic_key: "kling.camera_strength", node_id: "27", input_name: "seed", value_type: "integer", required: true }] });
    expect(screen.getByRole("button", { name: "Update workflow" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import workflow" })).not.toBeInTheDocument();
  });

  it("opens saved workflow editing in place on the workflows page", async () => {
    window.history.replaceState(null, "", "/workflows");
    const template = {
      id: "workflow-1", logical_id: "workflow-1", name: "LTX workflow", description: null, renderer_provider: "comfyui", workflow_json: { "1": { class_type: "Text", inputs: { text: "Hello" } } }, metadata_json: {}, version: 1, checksum: "checksum", bindings: [], created_at: "2026-08-08T12:00:00Z", updated_at: "2026-08-08T12:00:00Z",
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("render-profiles")) return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify({ items: [template], total: 1 }), { status: 200, headers: { "content-type": "application/json" } });
    });

    render(<Providers><WorkflowWorkspace /></Providers>);
    expect(screen.getByRole("tab", { name: "Workflows" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("button", { name: "Edit LTX workflow" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Show LTX workflow details" }));

    const details = document.getElementById("workflow-details-workflow-1");
    expect(details).not.toBeNull();
    await waitFor(() => expect(within(details as HTMLElement).getByLabelText("Template name")).toHaveValue("LTX workflow"));
    expect(within(details as HTMLElement).getByRole("button", { name: "Update workflow" })).toBeVisible();
    expect(window.location.pathname).toBe("/workflows");
  });

  it("edits an LTX control in the same row instead of a nested second row", () => {
    window.sessionStorage.setItem("workflow-template-edit", JSON.stringify({
      id: "workflow-ltx",
      logical_id: "workflow-ltx",
      name: "LTX 2.3 workflow",
      description: null,
      renderer_provider: "comfyui",
      workflow_json: {
        "269": { class_type: "LoadImage", inputs: { image: "source.png" } },
        "340:319": { _meta: { title: "LTX 2.3 Prompt" }, class_type: "PrimitiveStringMultiline", inputs: { value: "Elena speaks." } },
        "340:285": { _meta: { title: "RandomNoise" }, class_type: "RandomNoise", inputs: { noise_seed: 42 } },
        "340:286": { _meta: { title: "RandomNoise" }, class_type: "RandomNoise", inputs: { noise_seed: 473920259086225 } },
        "340:289": { _meta: { title: "ManualSigmas" }, class_type: "ManualSigmas", inputs: { sigmas: "0.85, 0.725, 0.0" } },
        "340:291": { _meta: { title: "SamplerCustomAdvanced" }, class_type: "SamplerCustomAdvanced", inputs: { noise: ["340:286", 0], sigmas: ["340:308", 0] } },
        "340:308": { _meta: { title: "ManualSigmas" }, class_type: "ManualSigmas", inputs: { sigmas: "1.0, 0.99375, 0.0" } },
        "340:310": { _meta: { title: "SamplerCustomAdvanced" }, class_type: "SamplerCustomAdvanced", inputs: { noise: ["340:285", 0], sigmas: ["340:289", 0] } },
        "340:346": { _meta: { title: "Generate LTX2 Prompt" }, class_type: "TextGenerateLTX2Prompt", inputs: { "sampling_mode.seed": 0 } },
        "340:350": { _meta: { title: "Empty LTX Video Latent" }, class_type: "EmptyLTXVLatentVideo", inputs: { width: 768, height: 1280 } },
      },
      metadata_json: { workflow_kind: "ltx-2.3" },
      version: 1,
      checksum: "checksum",
      bindings: [],
      created_at: "2026-08-08T12:00:00Z",
      updated_at: "2026-08-08T12:00:00Z",
    }));

    render(<Providers><WorkflowTemplateSetup /></Providers>);

    expect(screen.getByText("Default source image")).toBeInTheDocument();
    expect(screen.getByText("Default audio")).toBeInTheDocument();
    const controls = screen.getByText("LTX 2.3 controls").closest(".workflow-tree-editor");
    const jsonSummary = screen.getByText("ComfyUI API workflow JSON", { selector: "summary" });
    const jsonDetails = jsonSummary.closest("details");
    expect(controls).not.toBeNull();
    expect(jsonDetails).not.toBeNull();
    expect(jsonDetails).toHaveAttribute("open");
    expect((controls as Node).compareDocumentPosition(jsonDetails as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: /Seed.*473920259086225/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Seed.*0$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Width.*768/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Height.*1280/i }));
    fireEvent.change(screen.getByDisplayValue("1280"), { target: { value: "1920" } });
    expect((screen.getByLabelText("ComfyUI API workflow JSON") as HTMLTextAreaElement).value).toContain('"height": 1920');
    fireEvent.click(screen.getByRole("button", { name: /Image source.*source\.png/i }));
    const input = screen.getByDisplayValue("source.png");
    const row = input.closest(".workflow-ltx-control");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Image source")).toBeInTheDocument();
    expect(input.closest("details")).toBeNull();
  });
});
