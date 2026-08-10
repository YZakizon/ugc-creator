import type { Job, RenderedWorkflowControl, WorkflowTemplate } from "@/lib/api";

type Scalar = string | number | boolean;
type Field = RenderedWorkflowControl & { classType: string; title: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function storedMediaName(workflow: WorkflowTemplate, key: "source_image" | "audio"): string | undefined {
  const media = workflow.metadata_json.default_workflow_media;
  if (!isRecord(media) || typeof media[key] !== "string") return undefined;
  return (media[key] as string).split("/").at(-1);
}

function expand(value: Scalar, values: Record<string, string | number | undefined>): Scalar {
  if (typeof value !== "string") return value;
  return value.replace(/\{\{([A-Z0-9_]+)\}\}/g, (token, key: string) => {
    const replacement = values[key];
    return replacement === undefined ? token : String(replacement);
  });
}

function fields(workflow: WorkflowTemplate, job: Job): Field[] {
  const values = {
    SCRIPT: job.speech_script ?? job.topic,
    TOPIC: job.topic,
    HOOK: job.hook ?? "",
    VIDEO_PROMPT: job.speech_script ?? job.topic,
    DURATION: job.target_duration_seconds,
    AUDIO: job.audio_asset?.filename ?? storedMediaName(workflow, "audio"),
    SOURCE_IMAGE: storedMediaName(workflow, "source_image"),
  };
  return Object.entries(workflow.workflow_json).flatMap(([nodeId, rawNode]) => {
    if (!isRecord(rawNode) || typeof rawNode.class_type !== "string" || !isRecord(rawNode.inputs)) return [];
    const title = isRecord(rawNode._meta) && typeof rawNode._meta.title === "string" ? rawNode._meta.title : "";
    return Object.entries(rawNode.inputs).flatMap(([inputName, rawValue]) => {
      if (typeof rawValue !== "string" && typeof rawValue !== "number" && typeof rawValue !== "boolean") return [];
      return [{
        label: "",
        node_id: nodeId,
        input_name: inputName,
        value: expand(rawValue, values),
        classType: rawNode.class_type as string,
        title,
      }];
    });
  });
}

function first(items: Field[], predicate: (field: Field) => boolean): Field | undefined {
  return items.find(predicate);
}

function linkedNodeId(value: unknown): string | undefined {
  return Array.isArray(value) && typeof value[0] === "string" ? value[0] : undefined;
}

function primarySeedField(workflow: WorkflowTemplate, items: Field[]): Field | undefined {
  const seeds = items.filter((field) => (
    typeof field.value === "number"
    && Number.isInteger(field.value)
    && /randomnoise/i.test(field.classType)
    && /(?:seed|noise[._-]?seed|.+\.seed)/i.test(field.input_name)
  ));

  const basePassSeed = seeds.find((seed) => {
    const sampler = Object.values(workflow.workflow_json).find((rawNode) => (
      isRecord(rawNode)
      && /samplercustomadvanced/i.test(String(rawNode.class_type ?? ""))
      && isRecord(rawNode.inputs)
      && linkedNodeId(rawNode.inputs.noise) === seed.node_id
    ));
    const sigmasNodeId = isRecord(sampler) && isRecord(sampler.inputs) ? linkedNodeId(sampler.inputs.sigmas) : undefined;
    const sigmasNode = sigmasNodeId ? workflow.workflow_json[sigmasNodeId] : undefined;
    const sigmas = isRecord(sigmasNode) && isRecord(sigmasNode.inputs) ? sigmasNode.inputs.sigmas : undefined;
    return typeof sigmas === "string" && /^\s*1(?:\.0+)?(?:\s*,|\s*$)/.test(sigmas);
  });

  return basePassSeed ?? seeds.at(-1) ?? first(items, (field) => (
    typeof field.value === "number"
    && Number.isInteger(field.value)
    && /(?:seed|noise[._-]?seed|.+\.seed)/i.test(field.input_name)
  ));
}

export function previewLtxRenderControls(workflow: WorkflowTemplate, job: Job): RenderedWorkflowControl[] {
  const items = fields(workflow, job);
  const numeric = (field: Field) => typeof field.value === "number";
  const controls: Array<[string, Field | undefined]> = [
    ["Image source", first(items, (field) => /loadimage/i.test(field.classType) && field.input_name === "image")],
    ["Audio source", first(items, (field) => /loadaudio/i.test(field.classType) && field.input_name === "audio")],
    ["Prompt", first(items, (field) => field.title.trim().toLowerCase() === "prompt")
      ?? first(items, (field) => /primitivestringmultiline/i.test(field.classType))],
    ["FPS", first(items, (field) => numeric(field) && (/^frame rate$/i.test(field.title.trim()) || /^fps$/i.test(field.input_name)))],
    ["Duration", first(items, (field) => numeric(field) && (/duration/i.test(field.title) || /^duration$/i.test(field.input_name)))],
    ["Seed", primarySeedField(workflow, items)],
    ["Width", first(items, (field) => numeric(field) && (/^width$/i.test(field.title.trim()) || /^width$/i.test(field.input_name)))],
    ["Height", first(items, (field) => numeric(field) && (/^height$/i.test(field.title.trim()) || /^height$/i.test(field.input_name)))],
  ];
  return controls.flatMap(([label, field]) => field ? [{ label, node_id: field.node_id, input_name: field.input_name, value: field.value }] : []);
}
