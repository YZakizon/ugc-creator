export type JobStatus =
  | "draft"
  | "generating_content"
  | "content_ready"
  | "generating_tts"
  | "tts_ready"
  | "fitting_duration"
  | "ready_to_render"
  | "queued"
  | "submitting_render"
  | "rendering"
  | "downloading_output"
  | "completed"
  | "failed"
  | "cancelled";

export type Job = {
  id: string;
  batch_id: string;
  topic: string;
  content_number: number;
  status: JobStatus;
  render_profile_id: string | null;
  voice_profile_id: string | null;
  workflow_template_id: string | null;
  target_duration_seconds: number;
  error_message: string | null;
  speech_script: string | null;
  hook: string | null;
  instagram_metadata: Record<string, unknown> | null;
  tiktok_metadata: Record<string, unknown> | null;
  llm_provider: string | null;
  llm_model: string | null;
  prompt_version: string | null;
  tts_provider: string | null;
  tts_voice_id: string | null;
  tts_model: string | null;
  tts_provider_request_id: string | null;
  audio_asset: MediaAsset | null;
  audio_assets: MediaAsset[];
  created_at: string;
  updated_at: string;
};

export type Batch = {
  id: string;
  name: string;
  status: "draft" | "processing" | "completed" | "failed";
  default_render_profile_id: string | null;
  target_duration_seconds: number;
  auto_fit_duration: boolean;
  job_count: number;
  created_at: string;
  updated_at: string;
  jobs: Job[];
};

export type Topic = {
  id: string;
  name: string;
  status: "draft" | "processing" | "completed" | "failed";
  default_render_profile_id: string | null;
  target_duration_seconds: number;
  auto_fit_duration: boolean;
  content_count: number;
  created_at: string;
  updated_at: string;
  contents: Job[];
};

export type TopicSummary = Omit<Topic, "contents">;

export type DashboardSummary = {
  in_progress: number;
  ready_to_render: number;
  completed_videos: number;
  render_profiles: number;
  recent_jobs: Job[];
};

export type VoiceProfile = {
  id: string;
  name: string;
  provider: string;
  provider_voice_id: string;
  provider_model: string | null;
  speed: number;
  stability: number | null;
  similarity: number | null;
  style_exaggeration: number | null;
  extra_settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type VoicePreview = {
  id: string;
  voice_profile_id: string;
  text: string;
  status: "queued" | "generating" | "completed" | "failed";
  provider: string;
  provider_request_id: string | null;
  generated_usage_units: number | null;
  account_used_units: number | null;
  account_limit_units: number | null;
  account_remaining_units: number | null;
  usage_resets_at_unix: number | null;
  usage_unit: string | null;
  content_type: string | null;
  filename: string | null;
  error_message: string | null;
  download_url: string | null;
  created_at: string;
  updated_at: string;
};

export type TTSAccountUsage = {
  provider: "elevenlabs";
  configured: boolean;
  used_units: number | null;
  limit_units: number | null;
  remaining_units: number | null;
  resets_at_unix: number | null;
  unit: string;
};

export type ElevenLabsVoice = {
  voice_id: string;
  name: string;
  category: string | null;
  description: string | null;
  preview_url: string | null;
};

export type Character = {
  id: string;
  name: string;
  slug: string;
};

export type RenderProfile = {
  id: string;
  name: string;
  character_id: string;
  voice_profile_id: string | null;
  renderer_provider: string;
  workflow_template_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type RenderedWorkflowControl = {
  label: string;
  node_id: string;
  input_name: string;
  value: unknown;
};

export type WorkflowTemplate = {
  id: string;
  logical_id: string;
  name: string;
  description: string | null;
  renderer_provider: "comfyui";
  workflow_json: Record<string, unknown>;
  metadata_json: Record<string, unknown>;
  version: number;
  checksum: string;
  bindings: Array<{
    id: string;
    semantic_key: string;
    node_id: string;
    input_name: string;
    value_type: string;
    required: boolean;
  }>;
  created_at: string;
  updated_at: string;
};

export type RenderNode = {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  is_active: boolean;
  health_status: "unknown" | "healthy" | "unavailable";
  health_message: string | null;
  health_checked_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ContentPromptSettings = {
  provider: "openai";
  prompt_template: string;
  prompt_version: string;
  default_prompt_template: string;
  supported_placeholders: string[];
};

export type MediaAsset = {
  id: string;
  job_id: string;
  kind: string;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  generation_metadata: {
    source?: string;
    provider?: string;
    voice_profile_id?: string;
    voice_id?: string;
    model?: string;
    settings?: Record<string, unknown>;
    provider_request_id?: string | null;
    script_sha256?: string;
    generated_at?: string;
  } | null;
  download_url: string;
  created_at: string;
};

export type RenderAttempt = {
  id: string;
  job_id: string;
  render_profile_id: string;
  render_node_id: string;
  workflow_template_id: string;
  provider: string;
  status: string;
  progress: number;
  external_job_id: string | null;
  error_message: string | null;
  output_filename: string | null;
  output_deleted_at: string | null;
  effective_values: Record<string, unknown>;
  rendered_controls: RenderedWorkflowControl[];
  created_at: string;
  updated_at: string;
  assets: MediaAsset[];
};

export type ResourceReference = { id: string; name: string };

export type VoiceProfileInUseDetail = {
  code: "voice_profile_in_use";
  message: string;
  render_profiles: ResourceReference[];
  characters: ResourceReference[];
};

export class ApiRequestError extends Error {
  constructor(message: string, public readonly detail: unknown) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = payload?.detail;
    const message = typeof detail === "string"
      ? detail
      : isErrorDetail(detail) && typeof detail.message === "string"
        ? detail.message
        : "Request failed";
    throw new ApiRequestError(message, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function isErrorDetail(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/api/v1/dashboard/summary");
}

export type CreateBatchInput = {
  name: string;
  topics: string[];
  default_render_profile_id?: string;
  target_duration_seconds: number;
  auto_fit_duration: boolean;
};

export function createBatch(input: CreateBatchInput): Promise<Batch> {
  return request<Batch>("/api/v1/batches", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getBatches(): Promise<{ items: Batch[]; total: number; limit: number; offset: number }> {
  return request<{ items: Batch[]; total: number; limit: number; offset: number }>("/api/v1/batches?limit=100");
}

export type CreateTopicInput = {
  topic: string;
  render_profile_id: string;
  target_duration_seconds: number;
  auto_fit_duration: boolean;
};

export function createTopic(input: CreateTopicInput): Promise<Topic> {
  return request<Topic>("/api/v1/topics", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createTopics(input: Omit<CreateTopicInput, "topic"> & { topics: string[] }): Promise<{ items: Topic[]; total: number }> {
  return request<{ items: Topic[]; total: number }>("/api/v1/topics/bulk", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getTopics(limit = 20, offset = 0): Promise<{ items: TopicSummary[]; total: number; limit: number; offset: number }> {
  return request<{ items: TopicSummary[]; total: number; limit: number; offset: number }>(`/api/v1/topics?limit=${limit}&offset=${offset}`);
}

export function getTopicContents(topicId: string, limit = 20, offset = 0): Promise<{ items: Job[]; total: number; limit: number; offset: number }> {
  return request<{ items: Job[]; total: number; limit: number; offset: number }>(`/api/v1/topics/${topicId}/contents?limit=${limit}&offset=${offset}`);
}

export function generateMoreContent(topicId: string): Promise<Job> {
  return request<Job>(`/api/v1/topics/${topicId}/contents`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function deleteTopic(topicId: string): Promise<void> {
  return request<void>(`/api/v1/topics/${topicId}`, { method: "DELETE" });
}

export function deleteContent(contentId: string): Promise<void> {
  return request<void>(`/api/v1/contents/${contentId}`, { method: "DELETE" });
}

export function updateJobRenderProfile(jobId: string, renderProfileId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/render-profile`, {
    method: "PATCH",
    body: JSON.stringify({ render_profile_id: renderProfileId }),
  });
}

export function updateJobVoiceProfile(jobId: string, voiceProfileId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/voice-profile`, {
    method: "PATCH",
    body: JSON.stringify({ voice_profile_id: voiceProfileId }),
  });
}

export function updateJobWorkflowTemplate(jobId: string, workflowTemplateId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/workflow-template`, {
    method: "PATCH",
    body: JSON.stringify({ workflow_template_id: workflowTemplateId }),
  });
}

export function uploadJobAudio(jobId: string, input: {
  filename: string;
  content_base64: string;
  content_type: string;
}): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/audio`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteMediaAsset(assetId: string): Promise<void> {
  return request<void>(`/api/v1/assets/${assetId}`, { method: "DELETE" });
}

export function generateJobContent(jobId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/generate-content`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function generateJobSpeech(jobId: string): Promise<Job> {
  return request<Job>(`/api/v1/jobs/${jobId}/generate-tts`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function createVoiceProfile(input: {
  name: string;
  provider: string;
  provider_voice_id: string;
  provider_model?: string;
  speed: number;
  stability?: number;
  similarity?: number;
  style_exaggeration?: number;
  extra_settings: Record<string, unknown>;
}): Promise<VoiceProfile> {
  return request<VoiceProfile>("/api/v1/voice-profiles", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateVoiceProfile(input: {
  id: string;
  name: string;
  provider: string;
  provider_voice_id: string;
  provider_model?: string;
  speed: number;
  stability?: number;
  similarity?: number;
  style_exaggeration?: number;
  extra_settings: Record<string, unknown>;
}): Promise<VoiceProfile> {
  const { id, ...payload } = input;
  return request<VoiceProfile>(`/api/v1/voice-profiles/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteVoiceProfile(profileId: string): Promise<void> {
  return request<void>(`/api/v1/voice-profiles/${profileId}`, { method: "DELETE" });
}

export function createVoicePreview(input: { voiceProfileId: string; text: string }): Promise<VoicePreview> {
  return request<VoicePreview>(`/api/v1/voice-profiles/${input.voiceProfileId}/previews`, {
    method: "POST",
    body: JSON.stringify({ text: input.text }),
  });
}

export function getVoicePreview(previewId: string): Promise<VoicePreview> {
  return request<VoicePreview>(`/api/v1/voice-previews/${previewId}`);
}

export function getVoicePreviews(voiceProfileId: string): Promise<{ items: VoicePreview[]; total: number }> {
  return request<{ items: VoicePreview[]; total: number }>(`/api/v1/voice-profiles/${voiceProfileId}/previews`);
}

export function deleteVoicePreview(previewId: string): Promise<void> {
  return request<void>(`/api/v1/voice-previews/${previewId}`, { method: "DELETE" });
}

export function getElevenLabsUsage(): Promise<TTSAccountUsage> {
  return request<TTSAccountUsage>("/api/v1/tts-providers/elevenlabs/usage");
}

export function getElevenLabsVoices(): Promise<{ items: ElevenLabsVoice[]; total: number }> {
  return request<{ items: ElevenLabsVoice[]; total: number }>("/api/v1/tts-providers/elevenlabs/voices");
}

export function createCharacter(input: {
  name: string;
  default_voice_profile_id: string;
}): Promise<Character> {
  return request<Character>("/api/v1/characters", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getCharacters(): Promise<{ items: Character[]; total: number }> {
  return request<{ items: Character[]; total: number }>("/api/v1/characters");
}

export function getVoiceProfiles(): Promise<{ items: VoiceProfile[]; total: number }> {
  return request<{ items: VoiceProfile[]; total: number }>("/api/v1/voice-profiles");
}

export function createRenderProfile(input: {
  name: string;
  character_id: string;
  voice_profile_id: string;
  renderer_provider: string;
  workflow_template_id?: string;
}): Promise<RenderProfile> {
  return request<RenderProfile>("/api/v1/render-profiles", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createRenderProfileSetup(input: {
  profile_name: string;
  character_name: string;
  voice_profile_id: string;
  renderer_provider: string;
  workflow_template_id?: string;
}): Promise<RenderProfile> {
  return request<RenderProfile>("/api/v1/render-profiles/setup", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getRenderProfiles(): Promise<{ items: RenderProfile[]; total: number }> {
  return request<{ items: RenderProfile[]; total: number }>("/api/v1/render-profiles");
}

export function updateRenderProfile(input: {
  id: string;
  name: string;
  character_name: string;
  voice_profile_id: string | null;
  workflow_template_id?: string;
}): Promise<RenderProfile> {
  return request<RenderProfile>(`/api/v1/render-profiles/${input.id}`, {
    method: "PATCH",
    body: JSON.stringify({
      name: input.name,
      character_name: input.character_name,
      voice_profile_id: input.voice_profile_id,
      workflow_template_id: input.workflow_template_id ?? null,
    }),
  });
}

export function deleteRenderProfile(profileId: string): Promise<void> {
  return request<void>(`/api/v1/render-profiles/${profileId}`, { method: "DELETE" });
}

export type WorkflowTemplateInput = {
  name: string;
  description?: string;
  metadata_json?: Record<string, unknown>;
  workflow_json: Record<string, unknown>;
  bindings: Array<{
    semantic_key: string;
    node_id: string;
    input_name: string;
    value_type: "string" | "template" | "integer" | "number" | "boolean";
    required: boolean;
  }>;
};

export function createWorkflowTemplate(input: WorkflowTemplateInput): Promise<WorkflowTemplate> {
  return request<WorkflowTemplate>("/api/v1/workflow-templates", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateWorkflowTemplate(templateId: string, input: WorkflowTemplateInput): Promise<WorkflowTemplate> {
  return request<WorkflowTemplate>(`/api/v1/workflow-templates/${templateId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function getWorkflowTemplates(): Promise<{ items: WorkflowTemplate[]; total: number }> {
  return request<{ items: WorkflowTemplate[]; total: number }>("/api/v1/workflow-templates");
}

export function deleteWorkflowTemplate(templateId: string): Promise<void> {
  return request<void>(`/api/v1/workflow-templates/${templateId}`, { method: "DELETE" });
}

export function uploadWorkflowMedia(input: {
  filename: string;
  content_base64: string;
  input_type: "image" | "audio";
}): Promise<{ asset_key: string; filename: string; input_type: "image" | "audio" }> {
  return request<{ asset_key: string; filename: string; input_type: "image" | "audio" }>("/api/v1/workflow-media", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getRenderNodes(): Promise<{ items: RenderNode[]; total: number }> {
  return request<{ items: RenderNode[]; total: number }>("/api/v1/render-nodes");
}

export function getContentPromptSettings(): Promise<ContentPromptSettings> {
  return request<ContentPromptSettings>("/api/v1/settings/content-generation");
}

export function updateContentPromptSettings(promptTemplate: string): Promise<ContentPromptSettings> {
  return request<ContentPromptSettings>("/api/v1/settings/content-generation", {
    method: "PUT",
    body: JSON.stringify({ prompt_template: promptTemplate }),
  });
}

export function createRenderNode(input: { name: string; base_url: string; is_active: boolean }): Promise<RenderNode> {
  return request<RenderNode>("/api/v1/render-nodes", { method: "POST", body: JSON.stringify(input) });
}

export function checkRenderNode(nodeId: string): Promise<RenderNode> {
  return request<RenderNode>(`/api/v1/render-nodes/${nodeId}/health`, { method: "POST", body: JSON.stringify({}) });
}

export function deleteRenderNode(nodeId: string): Promise<void> {
  return request<void>(`/api/v1/render-nodes/${nodeId}`, { method: "DELETE" });
}

export function queueJobRender(jobId: string, nodeId: string): Promise<RenderAttempt> {
  return request<RenderAttempt>(`/api/v1/jobs/${jobId}/render?node_id=${encodeURIComponent(nodeId)}`, { method: "POST", body: JSON.stringify({}) });
}

export function getRenderAttempts(): Promise<{ items: RenderAttempt[]; total: number }> {
  return request<{ items: RenderAttempt[]; total: number }>("/api/v1/render-attempts");
}
