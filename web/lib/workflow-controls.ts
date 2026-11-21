import type { WorkflowTemplate } from "@/lib/api";

export type OptionalImageReference = {
  key: string;
  label: string;
  enabled: boolean;
  asset_key?: string;
};

export const IMAGE_ASPECT_RATIOS = ["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)", "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"];

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function minimaxImageSize(workflow?: WorkflowTemplate) {
  if (!workflow) return null;
  for (const node of Object.values(workflow.workflow_json)) {
    if (!record(node) || node.class_type !== "MiniMaxH3ReferenceToVideo" || !record(node.inputs)) continue;
    const { width, height } = node.inputs;
    if (!Array.isArray(width) || !Array.isArray(height) || width[0] !== height[0]) continue;
    const selector = workflow.workflow_json[String(width[0])];
    if (!record(selector) || selector.class_type !== "ResolutionSelector" || !record(selector.inputs)) continue;
    const inputs = selector.inputs;
    if (typeof inputs.megapixels !== "number" || typeof inputs.aspect_ratio !== "string" || typeof inputs.multiple !== "number") continue;
    return { nodeId: String(width[0]), megapixels: inputs.megapixels, aspectRatio: inputs.aspect_ratio, multiple: inputs.multiple };
  }
  return null;
}

export function optionalImageReferences(workflow?: WorkflowTemplate): OptionalImageReference[] {
  const references = workflow?.metadata_json.optional_image_references;
  if (!Array.isArray(references)) return [];
  return references.flatMap((reference: unknown) => {
    if (!reference || typeof reference !== "object" || !("key" in reference) || typeof reference.key !== "string") return [];
    return [{
      key: reference.key,
      label: "label" in reference && typeof reference.label === "string" ? reference.label : "Second image reference",
      enabled: "enabled" in reference && reference.enabled === true,
      asset_key: "asset_key" in reference && typeof reference.asset_key === "string" ? reference.asset_key : undefined,
    }];
  });
}
