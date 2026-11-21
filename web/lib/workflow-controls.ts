import type { WorkflowTemplate } from "@/lib/api";

export type OptionalImageReference = {
  key: string;
  label: string;
  enabled: boolean;
  asset_key?: string;
};

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
