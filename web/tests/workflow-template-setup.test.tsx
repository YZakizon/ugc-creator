import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Providers } from "../app/providers";
import { WorkflowTemplateSetup } from "../components/workflow-template-setup";

describe("workflow template setup", () => {
  afterEach(() => {
    cleanup();
    window.sessionStorage.clear();
  });

  it("preserves custom semantic bindings while raw workflow JSON is edited", async () => {
    window.sessionStorage.setItem("workflow-template-edit", JSON.stringify({
      id: "workflow-1",
      name: "Custom workflow",
      description: null,
      renderer_provider: "comfyui",
      workflow_json: {
        "27": { class_type: "KSampler", inputs: { seed: 42, steps: 20 } },
      },
      metadata_json: {},
      version: 1,
      checksum: "checksum",
      bindings: [{ id: "binding-1", semantic_key: "seed", node_id: "27", input_name: "seed", value_type: "integer", required: true }],
      created_at: "2026-08-07T12:00:00Z",
      updated_at: "2026-08-07T12:00:00Z",
    }));

    render(<Providers><WorkflowTemplateSetup /></Providers>);

    expect(await screen.findByLabelText("Binding 1 parameter")).toHaveValue("seed");
    fireEvent.change(screen.getByLabelText("ComfyUI API workflow JSON"), {
      target: { value: JSON.stringify({ "27": { class_type: "KSampler", inputs: { seed: 99, steps: 25 } } }, null, 2) },
    });

    expect(screen.getByLabelText("Binding 1 parameter")).toHaveValue("seed");
    expect(screen.getByLabelText("Binding 1 workflow node input")).toHaveValue("27::seed");
  });
});
