"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { HumanDate } from "@/components/date-display";
import { Toast } from "@/components/feedback";
import {
  attachJobElevenLabsVoice,
  cancelRenderAttempt,
  cloneOnDemandVideo,
  createWorkflowTemplate,
  createOnDemandVideo,
  deleteMediaAsset,
  deleteTopic,
  generateJobContent,
  generateJobSpeech,
  getElevenLabsUsage,
  getElevenLabsVoices,
  getOnDemandVideos,
  getRenderAttempts,
  getRenderNodes,
  getRenderProfiles,
  getTopic,
  getWorkflowTemplates,
  queueJobRender,
  selectJobAudio,
  updateJobRenderOverrides,
  updateJobScript,
  updateOnDemandVideo,
  uploadJobAudio,
  uploadJobSourceImage,
} from "@/lib/api";
import { previewLtxRenderControls } from "@/lib/render-settings-preview";
import type { ElevenLabsVoice, Job, MediaAsset, OnDemandRenderOverrides, RenderAttempt, RenderedWorkflowControl, Topic, TopicSummary, WorkflowTemplate, WorkflowTemplateInput } from "@/lib/api";

const ACTIVE_STATUSES = new Set(["generating_content", "generating_tts", "queued", "submitting_render", "rendering", "downloading_output"]);
const CANCELABLE_RENDER_STATUSES = new Set(["queued", "submitting_render", "rendering", "downloading_output"]);
const TERMINAL_RENDER_STATUSES = new Set(["completed", "failed", "cancelled"]);
const CREATE_VIDEO_LAST_SETTINGS_KEY = "ugc-create-video-last-settings-v1";

type CreateVideoLastSettings = {
  render_profile_id?: string;
  workflow_template_id?: string;
  voice_id?: string;
  video_prompt?: string;
  fps?: string;
  duration?: string;
  seed?: string;
  audio_controls_open?: boolean;
  voice_speed?: string;
  voice_stability?: string;
  voice_similarity?: string;
  voice_style?: string;
  voice_output_format?: string;
  voice_speaker_boost?: boolean;
};

function firstContent(jobTopic?: { contents?: Job[] }): Job | null {
  return jobTopic?.contents?.[0] ?? null;
}

function renderProgress(attempt?: RenderAttempt): string {
  if (!attempt) return "No render yet";
  if (attempt.status === "rendering" && attempt.progress <= 1) return "Rendering · progress unavailable";
  return `${attempt.status.replaceAll("_", " ")} · ${attempt.progress}%`;
}

function formatElapsedTime(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (totalMinutes > 0) return `${totalMinutes}m ${seconds}s`;
  return `${seconds}s`;
}

function renderElapsedTime(attempt?: RenderAttempt, nowMs = Date.now()): string | null {
  if (!attempt) return null;
  const start = Date.parse(attempt.submitted_at ?? attempt.created_at);
  const end = attempt.completed_at
    ? Date.parse(attempt.completed_at)
    : TERMINAL_RENDER_STATUSES.has(attempt.status)
      ? Date.parse(attempt.updated_at)
      : nowMs;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return formatElapsedTime(end - start);
}

function RenderElapsed({ attempt, nowMs }: { attempt: RenderAttempt; nowMs?: number }) {
  const elapsed = renderElapsedTime(attempt, nowMs);
  if (!elapsed) return null;
  return <span className="render-elapsed">elapsed {elapsed}</span>;
}

function formatUsage(usage?: Awaited<ReturnType<typeof getElevenLabsUsage>>): string {
  if (!usage) return "Loading balance…";
  if (!usage.configured) return "ElevenLabs is not configured";
  if (usage.remaining_units === null) return `Balance unavailable · ${usage.unit}`;
  return `${usage.remaining_units.toLocaleString()} ${usage.unit} remaining`;
}

function voiceLabel(voice: ElevenLabsVoice): string {
  return [voice.name, voice.category].filter(Boolean).join(" · ");
}

function durationFromAudioAsset(asset: MediaAsset | null | undefined): string | null {
  const seconds = asset?.generation_metadata?.duration_seconds;
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return null;
  return String(Math.max(1, Math.min(180, Math.ceil(seconds + 1))));
}

function activeAudioAsset(job: Job | null | undefined): MediaAsset | null {
  return job?.audio_asset ?? job?.audio_assets?.find((asset) => asset.kind === "audio") ?? null;
}

function latestGeneratedAudioAsset(job: Job | null | undefined): MediaAsset | null {
  return job?.audio_assets?.find((asset) => asset.generation_metadata?.source === "tts") ?? null;
}

function defaultRenderAudioAsset(job: Job | null | undefined): MediaAsset | null {
  return latestGeneratedAudioAsset(job) ?? activeAudioAsset(job);
}

function mediaDisplayName(asset: MediaAsset | null | undefined): string {
  return asset?.generation_metadata?.original_filename ?? asset?.filename ?? "";
}

function InfoTooltip({ label }: { label: string }) {
  return <span className="control-tooltip" aria-hidden="true" title={label}>?</span>;
}

function renderedParameterValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined) return "Not set";
  return JSON.stringify(value, null, 2) ?? String(value);
}

function RenderedLtxParamsDialog({ controls, onClose }: { controls: RenderedWorkflowControl[] | null; onClose: () => void }) {
  useEffect(() => {
    if (!controls) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [controls, onClose]);

  if (!controls) return null;

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="render-params-dialog" role="dialog" aria-modal="true" aria-labelledby="create-video-render-params-title"><div className="render-params-heading"><div><h2 id="create-video-render-params-title">Rendered LTX 2.3 params</h2><p>Actual ComfyUI control values used for this render, with variables expanded.</p></div><button className="toast-close" type="button" aria-label="Close rendered LTX params" onClick={onClose}>×</button></div>{controls.length ? <div className="render-params-list">{controls.map((control) => <article className="render-param" key={`${control.node_id}-${control.input_name}`}><div><strong>{control.label}</strong><small>{control.node_id}.{control.input_name}</small></div><pre>{renderedParameterValue(control.value)}</pre></article>)}</div> : <p className="render-params-empty">No rendered LTX controls were captured for this attempt.</p>}</section></div>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readLastCreateVideoSettings(): CreateVideoLastSettings | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CREATE_VIDEO_LAST_SETTINGS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isRecord(parsed) ? parsed as CreateVideoLastSettings : null;
  } catch {
    return null;
  }
}

function writeLastCreateVideoSettings(settings: CreateVideoLastSettings): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(CREATE_VIDEO_LAST_SETTINGS_KEY, JSON.stringify(settings));
}

async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result ?? "");
      resolve(value.includes(",") ? value.split(",")[1] : value);
    };
    reader.onerror = () => reject(new Error("The selected file could not be read."));
    reader.readAsDataURL(file);
  });
}

function workflowInputs(workflow: Record<string, unknown>) {
  return Object.entries(workflow).flatMap(([nodeId, node]) => {
    if (!isRecord(node) || !isRecord(node.inputs) || typeof node.class_type !== "string") return [];
    return Object.keys(node.inputs).map((inputName) => ({ nodeId, inputName, classType: node.class_type as string }));
  });
}

function suggestedWorkflowBindings(workflow: Record<string, unknown>): WorkflowTemplateInput["bindings"] {
  const inputs = workflowInputs(workflow);
  const image = inputs.find((input) => input.inputName === "image" && /loadimage/i.test(input.classType));
  const audio = inputs.find((input) => input.inputName === "audio" && /loadaudio/i.test(input.classType));
  const script = inputs.find((input) => /primitivestringmultiline/i.test(input.classType))
    ?? inputs.find((input) => ["text", "prompt", "value"].includes(input.inputName));
  return ([
    ["script", script, "template"],
    ["source_image", image, "string"],
    ["audio", audio, "string"],
  ] as const).flatMap(([semanticKey, input, valueType]) => input ? [{ semantic_key: semanticKey, node_id: input.nodeId, input_name: input.inputName, value_type: valueType, required: true }] : []);
}

function controlValue(workflow: WorkflowTemplate, label: string, job: Job | null): unknown {
  const fallbackJob = job ?? {
    id: "preview",
    batch_id: "preview",
    topic: "Created video",
    content_number: 1,
    status: "draft",
    render_profile_id: null,
    voice_profile_id: null,
    workflow_template_id: workflow.id,
    target_duration_seconds: 30,
    error_message: null,
    speech_script: null,
    hook: null,
    instagram_metadata: null,
    tiktok_metadata: null,
    llm_provider: null,
    llm_model: null,
    prompt_version: null,
    tts_provider: null,
    tts_voice_id: null,
    tts_model: null,
    tts_provider_request_id: null,
    render_overrides: {},
    audio_asset: null,
    audio_assets: [],
    created_at: new Date(0).toISOString(),
    updated_at: new Date(0).toISOString(),
  } satisfies Job;
  return previewLtxRenderControls(workflow, fallbackJob).find((control) => control.label === label)?.value;
}

export function CreateVideoPanel({ topicId, onSaved }: { topicId?: string | null; onSaved?: (topicId: string) => void }) {
  const queryClient = useQueryClient();
  const [currentTopicId, setCurrentTopicId] = useState<string | null>(topicId ?? null);
  const [title, setTitle] = useState("");
  const [script, setScript] = useState("");
  const [renderProfileId, setRenderProfileId] = useState("");
  const [workflowTemplateId, setWorkflowTemplateId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [videoPrompt, setVideoPrompt] = useState("");
  const [fps, setFps] = useState("24");
  const [duration, setDuration] = useState("30");
  const [seed, setSeed] = useState("");
  const [audioControlsOpen, setAudioControlsOpen] = useState(true);
  const [voiceSpeed, setVoiceSpeed] = useState("1");
  const [voiceStability, setVoiceStability] = useState("50");
  const [voiceSimilarity, setVoiceSimilarity] = useState("75");
  const [voiceStyle, setVoiceStyle] = useState("50");
  const [voiceOutputFormat, setVoiceOutputFormat] = useState("mp3_44100_128");
  const [voiceSpeakerBoost, setVoiceSpeakerBoost] = useState(true);
  const [selectedAudioAssetId, setSelectedAudioAssetId] = useState("");
  const [pendingSourceImageName, setPendingSourceImageName] = useState("");
  const [pendingAudioFileName, setPendingAudioFileName] = useState("");
  const [toast, setToast] = useState<{ message: string; variant: "success" | "danger" | "info" } | null>(null);
  const [renderPreflightError, setRenderPreflightError] = useState<string | null>(null);
  const [renderedLtxParams, setRenderedLtxParams] = useState<RenderedWorkflowControl[] | null>(null);
  const [autosaveState, setAutosaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [renderNowMs, setRenderNowMs] = useState(() => Date.now());
  const syncedScriptRef = useRef<string | null>(null);
  const loadedJobIdRef = useRef<string | null>(null);
  const scriptDirtyRef = useRef(false);
  const lastSettingsLoadedRef = useRef(false);
  const lastAutosaveKeyRef = useRef("");
  const awaitingAudioToastRef = useRef(false);
  const audioCountBeforeGenerateRef = useRef(0);
  const audioIdBeforeGenerateRef = useRef<string | null>(null);
  const pendingAudioSelectionRef = useRef<string | null>(null);
  const manualAudioSelectionRef = useRef<string | null>(null);
  const lastAppliedAudioDurationAssetIdRef = useRef<string | null>(null);
  const videoPromptRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => setCurrentTopicId(topicId ?? null), [topicId]);

  useEffect(() => {
    if (lastSettingsLoadedRef.current || currentTopicId) return;
    lastSettingsLoadedRef.current = true;
    const settings = readLastCreateVideoSettings();
    if (!settings) return;
    if (typeof settings.render_profile_id === "string") setRenderProfileId(settings.render_profile_id);
    if (typeof settings.workflow_template_id === "string") setWorkflowTemplateId(settings.workflow_template_id);
    if (typeof settings.voice_id === "string") setVoiceId(settings.voice_id);
    if (typeof settings.video_prompt === "string") setVideoPrompt(settings.video_prompt);
    if (typeof settings.fps === "string") setFps(settings.fps);
    if (typeof settings.duration === "string") setDuration(settings.duration);
    if (typeof settings.seed === "string") setSeed(settings.seed);
    if (typeof settings.audio_controls_open === "boolean") setAudioControlsOpen(settings.audio_controls_open);
    if (typeof settings.voice_speed === "string") setVoiceSpeed(settings.voice_speed);
    if (typeof settings.voice_stability === "string") setVoiceStability(settings.voice_stability);
    if (typeof settings.voice_similarity === "string") setVoiceSimilarity(settings.voice_similarity);
    if (typeof settings.voice_style === "string") setVoiceStyle(settings.voice_style);
    if (typeof settings.voice_output_format === "string") setVoiceOutputFormat(settings.voice_output_format);
    if (typeof settings.voice_speaker_boost === "boolean") setVoiceSpeakerBoost(settings.voice_speaker_boost);
  }, [currentTopicId]);

  const topic = useQuery({
    queryKey: ["on-demand-video", currentTopicId],
    queryFn: () => getTopic(currentTopicId as string),
    enabled: Boolean(currentTopicId),
    refetchInterval: 5000,
  });
  const profiles = useQuery({ queryKey: ["render-profiles"], queryFn: getRenderProfiles });
  const elevenVoices = useQuery({ queryKey: ["elevenlabs-voices"], queryFn: getElevenLabsVoices });
  const usage = useQuery({ queryKey: ["elevenlabs-usage"], queryFn: getElevenLabsUsage, refetchInterval: 15000 });
  const nodes = useQuery({ queryKey: ["render-nodes"], queryFn: getRenderNodes });
  const attempts = useQuery({ queryKey: ["render-attempts"], queryFn: getRenderAttempts, refetchInterval: 5000 });
  const workflows = useQuery({ queryKey: ["workflow-templates"], queryFn: getWorkflowTemplates });
  const renderProfiles = useMemo(() => profiles.data?.items ?? [], [profiles.data?.items]);
  const voices = useMemo(() => elevenVoices.data?.items ?? [], [elevenVoices.data?.items]);
  const renderNodes = useMemo(() => nodes.data?.items ?? [], [nodes.data?.items]);
  const renderAttempts = useMemo(() => attempts.data?.items ?? [], [attempts.data?.items]);
  const workflowTemplates = useMemo(() => workflows.data?.items ?? [], [workflows.data?.items]);
  const currentJob = firstContent(topic.data);
  const jobAttempts = useMemo(
    () => renderAttempts.filter((attempt) => attempt.job_id === currentJob?.id && !attempt.output_deleted_at),
    [renderAttempts, currentJob?.id],
  );
  const latestAttempt = jobAttempts[0];
  const latestAttemptId = latestAttempt?.id;
  const latestAttemptStatus = latestAttempt?.status;
  const active = currentJob ? ACTIVE_STATUSES.has(currentJob.status) : false;
  const selectedWorkflow = workflowTemplates.find((workflow) => workflow.id === workflowTemplateId);
  const firstProfile = renderProfiles.find((profile) => profile.id === renderProfileId);
  const selectedAudioAsset = currentJob?.audio_assets?.find((asset) => asset.id === selectedAudioAssetId) ?? defaultRenderAudioAsset(currentJob);
  const sourceImageDisplayName = pendingSourceImageName || mediaDisplayName(currentJob?.source_image_asset);
  const audioFileDisplayName = pendingAudioFileName || mediaDisplayName(currentJob?.audio_asset);

  useEffect(() => {
    if (!latestAttemptStatus || !CANCELABLE_RENDER_STATUSES.has(latestAttemptStatus)) return;
    setRenderNowMs(Date.now());
    const interval = window.setInterval(() => setRenderNowMs(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [latestAttemptId, latestAttemptStatus]);

  useEffect(() => {
    if (!topic.data) return;
    const job = firstContent(topic.data);
    const createVideoSettings = isRecord(job?.render_overrides?.create_video) ? job.render_overrides.create_video : {};
    setTitle(topic.data.name);
    setRenderProfileId(topic.data.default_render_profile_id ?? "");
    setWorkflowTemplateId(job?.workflow_template_id ?? (typeof createVideoSettings.workflow_template_id === "string" ? createVideoSettings.workflow_template_id : ""));
    if ((job?.id ?? null) !== loadedJobIdRef.current) {
      loadedJobIdRef.current = job?.id ?? null;
      manualAudioSelectionRef.current = null;
      pendingAudioSelectionRef.current = null;
      lastAppliedAudioDurationAssetIdRef.current = job?.audio_asset?.id ?? null;
      setDuration(String((job?.render_overrides?.duration as number | undefined) ?? topic.data.target_duration_seconds ?? 30));
      setScript(job?.speech_script ?? "");
      syncedScriptRef.current = job?.speech_script ?? null;
      scriptDirtyRef.current = false;
    }
    setVideoPrompt(String(job?.render_overrides?.video_prompt ?? ""));
    setFps(String(job?.render_overrides?.fps ?? 24));
    setSeed(job?.render_overrides?.seed === undefined ? "" : String(job.render_overrides.seed));
    if (typeof createVideoSettings.voice_speed === "number") setVoiceSpeed(String(createVideoSettings.voice_speed));
    if (typeof createVideoSettings.voice_stability === "number") setVoiceStability(String(Math.round(createVideoSettings.voice_stability * 100)));
    if (typeof createVideoSettings.voice_similarity === "number") setVoiceSimilarity(String(Math.round(createVideoSettings.voice_similarity * 100)));
    if (typeof createVideoSettings.voice_style_exaggeration === "number") setVoiceStyle(String(Math.round(createVideoSettings.voice_style_exaggeration * 100)));
    if (typeof createVideoSettings.voice_output_format === "string") setVoiceOutputFormat(createVideoSettings.voice_output_format);
    if (typeof createVideoSettings.voice_speaker_boost === "boolean") setVoiceSpeakerBoost(createVideoSettings.voice_speaker_boost);
    if (typeof createVideoSettings.voice_id === "string") setVoiceId(createVideoSettings.voice_id);
  }, [topic.data]);

  useEffect(() => {
    if (!renderProfileId && renderProfiles[0]) {
      setRenderProfileId(renderProfiles[0].id);
    }
  }, [renderProfiles, renderProfileId]);

  useEffect(() => {
    if (!workflowTemplateId && firstProfile?.workflow_template_id) {
      setWorkflowTemplateId(firstProfile.workflow_template_id);
    }
  }, [firstProfile?.workflow_template_id, workflowTemplateId]);

  useEffect(() => {
    const activeAudioId = defaultRenderAudioAsset(currentJob)?.id ?? "";
    const manualAudioId = manualAudioSelectionRef.current;
    if (manualAudioId) {
      const manualAudioStillExists = currentJob?.audio_assets?.some((asset) => asset.id === manualAudioId) ?? false;
      if (manualAudioStillExists) {
        setSelectedAudioAssetId(manualAudioId);
        return;
      }
      manualAudioSelectionRef.current = null;
    }
    if (pendingAudioSelectionRef.current) {
      if (activeAudioId === pendingAudioSelectionRef.current) {
        pendingAudioSelectionRef.current = null;
      } else {
        return;
      }
    }
      setSelectedAudioAssetId(activeAudioId);
  }, [currentJob]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["on-demand-videos"] });
    void queryClient.invalidateQueries({ queryKey: ["on-demand-video"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["render-attempts"] });
    void queryClient.invalidateQueries({ queryKey: ["elevenlabs-usage"] });
  };

  const renderOverrides = useCallback((durationOverride?: string): OnDemandRenderOverrides => {
    const effectiveDuration = durationOverride ?? duration;
    return {
      video_prompt: videoPrompt.trim() || null,
      fps: Number.parseInt(fps, 10) || null,
      duration: Number.parseInt(effectiveDuration, 10) || null,
      seed: seed.trim() ? Number.parseInt(seed, 10) : null,
      create_video: {
        workflow_template_id: workflowTemplateId || null,
        voice_id: voiceId || null,
        voice_speed: Number(voiceSpeed),
        voice_stability: Number(voiceStability) / 100,
        voice_similarity: Number(voiceSimilarity) / 100,
        voice_style_exaggeration: Number(voiceStyle) / 100,
        voice_output_format: voiceOutputFormat,
        voice_speaker_boost: voiceSpeakerBoost,
      },
    };
  }, [duration, fps, seed, videoPrompt, voiceId, voiceOutputFormat, voiceSimilarity, voiceSpeakerBoost, voiceSpeed, voiceStability, voiceStyle, workflowTemplateId]);
  const currentRenderedControls = useMemo(() => {
    if (!selectedWorkflow || !currentJob) return [];
    return previewLtxRenderControls(selectedWorkflow, {
      ...currentJob,
      audio_asset: selectedAudioAsset ?? currentJob.audio_asset,
      source_image_asset: sourceImageDisplayName
        ? {
            ...(currentJob.source_image_asset ?? {
              id: "pending-source-image",
              job_id: currentJob.id,
              kind: "source_image",
              content_type: null,
              size_bytes: 0,
              generation_metadata: null,
              download_url: "",
              created_at: new Date(0).toISOString(),
            }),
            filename: sourceImageDisplayName,
          }
        : currentJob.source_image_asset,
      render_overrides: renderOverrides(),
      target_duration_seconds: Number.parseInt(duration, 10) || currentJob.target_duration_seconds,
    });
  }, [currentJob, duration, renderOverrides, selectedAudioAsset, selectedWorkflow, sourceImageDisplayName]);

  const saveInput = useCallback(() => {
    return {
      title: title.trim(),
      render_profile_id: renderProfileId,
      workflow_template_id: workflowTemplateId || null,
      target_duration_seconds: Number.parseInt(duration, 10) || 30,
      speech_script: script.trim() || null,
      render_overrides: renderOverrides(),
    };
  }, [duration, renderOverrides, renderProfileId, script, title, workflowTemplateId]);

  useEffect(() => {
    if (!lastSettingsLoadedRef.current && !currentTopicId) return;
    writeLastCreateVideoSettings({
      render_profile_id: renderProfileId,
      workflow_template_id: workflowTemplateId,
      voice_id: voiceId,
      video_prompt: videoPrompt,
      fps,
      duration,
      seed,
      audio_controls_open: audioControlsOpen,
      voice_speed: voiceSpeed,
      voice_stability: voiceStability,
      voice_similarity: voiceSimilarity,
      voice_style: voiceStyle,
      voice_output_format: voiceOutputFormat,
      voice_speaker_boost: voiceSpeakerBoost,
    });
  }, [
    audioControlsOpen,
    currentTopicId,
    duration,
    fps,
    renderProfileId,
    seed,
    videoPrompt,
    voiceId,
    voiceOutputFormat,
    voiceSimilarity,
    voiceSpeakerBoost,
    voiceSpeed,
    voiceStability,
    voiceStyle,
    workflowTemplateId,
  ]);

  function elevenLabsPayload(voice: ElevenLabsVoice) {
    return {
      voice_id: voice.voice_id,
      name: voice.name,
      model: "eleven_multilingual_v2",
      speed: Number(voiceSpeed),
      stability: Number(voiceStability) / 100,
      similarity: Number(voiceSimilarity) / 100,
      style_exaggeration: Number(voiceStyle) / 100,
      output_format: voiceOutputFormat,
      speaker_boost: voiceSpeakerBoost,
    };
  }

  const applyWorkflowBase = useCallback((workflow: WorkflowTemplate, force = false) => {
    const prompt = controlValue(workflow, "Prompt", currentJob);
    const workflowFps = controlValue(workflow, "FPS", currentJob);
    const workflowDuration = controlValue(workflow, "Duration", currentJob);
    const workflowSeed = controlValue(workflow, "Seed", currentJob);
    if ((force || !videoPrompt.trim()) && typeof prompt === "string") setVideoPrompt(prompt);
    if ((force || !fps.trim()) && typeof workflowFps === "number") setFps(String(workflowFps));
    if ((force || !duration.trim()) && typeof workflowDuration === "number") setDuration(String(workflowDuration));
    if ((force || !seed.trim()) && typeof workflowSeed === "number") setSeed(String(workflowSeed));
  }, [currentJob, duration, fps, seed, videoPrompt]);

  useEffect(() => {
    if (selectedWorkflow && !currentJob?.render_overrides) applyWorkflowBase(selectedWorkflow);
  }, [selectedWorkflow, currentJob?.render_overrides, applyWorkflowBase]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const input = saveInput();
      return currentTopicId ? updateOnDemandVideo(currentTopicId, input) : createOnDemandVideo(input);
    },
    onSuccess: (saved) => {
      setCurrentTopicId(saved.id);
      onSaved?.(saved.id);
      invalidate();
    },
  });

  async function ensureSaved(): Promise<Job> {
    const saved = await saveMutation.mutateAsync();
    const job = saved.contents[0];
    if (!job) throw new Error("Created video has no editable content");
    return job;
  }

  function cacheUpdatedJob(updatedJob: Job): void {
    if (!currentTopicId) return;
    queryClient.setQueryData<Topic | undefined>(["on-demand-video", currentTopicId], (existing) => {
      if (!existing?.contents) return existing;
      return {
        ...existing,
        contents: existing.contents.map((item) => item.id === updatedJob.id ? updatedJob : item),
      };
    });
  }

  const generateScript = useMutation({
    mutationFn: async () => {
      const job = await ensureSaved();
      return generateJobContent(job.id);
    },
    onSuccess: () => {
      scriptDirtyRef.current = false;
      invalidate();
    },
  });

  const attachVoice = useMutation({
    mutationFn: ({ jobId, voice }: { jobId: string; voice: ElevenLabsVoice }) => attachJobElevenLabsVoice(jobId, elevenLabsPayload(voice)),
    onSuccess: invalidate,
  });

  const generateAudio = useMutation({
    mutationFn: async () => {
      const job = await ensureSaved();
      if (!script.trim()) throw new Error("Enter an audio script first.");
      const selectedVoice = voices.find((voice) => voice.voice_id === voiceId);
      if (!selectedVoice) throw new Error("Pick an ElevenLabs voice first.");
      audioCountBeforeGenerateRef.current = currentJob?.audio_assets?.length ?? 0;
      audioIdBeforeGenerateRef.current = currentJob?.audio_asset?.id ?? null;
      await attachJobElevenLabsVoice(job.id, elevenLabsPayload(selectedVoice));
      await updateJobScript(job.id, script);
      return generateJobSpeech(job.id);
    },
    onSuccess: () => {
      awaitingAudioToastRef.current = true;
      invalidate();
    },
  });

  const saveOverrides = useMutation({
    mutationFn: async () => {
      const job = await ensureSaved();
      return updateJobRenderOverrides(job.id, renderOverrides());
    },
    onSuccess: invalidate,
  });

  const applyAudioDuration = useCallback((asset: MediaAsset | null | undefined): string | null => {
    const nextDuration = durationFromAudioAsset(asset);
    if (!nextDuration) return null;
    setDuration(nextDuration);
    if (asset?.id) lastAppliedAudioDurationAssetIdRef.current = asset.id;
    return nextDuration;
  }, []);

  const generateVideo = useMutation({
    mutationFn: async () => {
      const selectedAudio = currentJob?.audio_assets?.find((asset) => asset.id === selectedAudioAssetId) ?? null;
      if (!currentJob?.source_image_asset || !selectedAudio) {
        throw new Error("Pick source image and audio file before generating video.");
      }
      const job = await ensureSaved();
      let durationOverride: string | undefined;
      if (selectedAudioAssetId && activeAudioAsset(job)?.id !== selectedAudioAssetId) {
        const updatedJob = await selectJobAudio(job.id, selectedAudioAssetId);
        cacheUpdatedJob(updatedJob);
        const selectedDuration = durationFromAudioAsset(activeAudioAsset(updatedJob));
        if (selectedDuration) {
          durationOverride = selectedDuration;
          setDuration(selectedDuration);
          lastAppliedAudioDurationAssetIdRef.current = selectedAudioAssetId;
        }
      }
      await updateJobRenderOverrides(job.id, renderOverrides(durationOverride));
      const node = renderNodes.find((item) => item.health_status === "healthy") ?? renderNodes.find((item) => item.is_active);
      if (!node) throw new Error("Add an active ComfyUI render node in Settings first.");
      return queueJobRender(job.id, node.id);
    },
    onSuccess: () => {
      setRenderPreflightError(null);
      invalidate();
    },
  });

  const cancelRender = useMutation({
    mutationFn: cancelRenderAttempt,
    onSuccess: () => {
      setToast({ message: "Rendering cancelled.", variant: "info" });
      invalidate();
    },
  });

  function handleGenerateVideo(): void {
    if (!currentJob?.source_image_asset || !selectedAudioAssetId) {
      const message = "Pick source image and audio file before generating video.";
      setRenderPreflightError(message);
      setToast({ message, variant: "danger" });
      return;
    }
    setRenderPreflightError(null);
    generateVideo.mutate();
  }

  const importWorkflow = useMutation({
    mutationFn: async (file: File) => {
      const parsed = JSON.parse(await file.text()) as unknown;
      if (!isRecord(parsed)) throw new Error("Import a ComfyUI API workflow JSON object.");
      return createWorkflowTemplate({
        name: `${title.trim() || file.name.replace(/\.json$/i, "") || "Create Video"} base LTX 2.3`,
        description: "Imported from Create Video as a base LTX 2.3 workflow.",
        workflow_json: parsed,
        metadata_json: {},
        bindings: suggestedWorkflowBindings(parsed),
      });
    },
    onSuccess: (workflow) => {
      setWorkflowTemplateId(workflow.id);
      applyWorkflowBase(workflow, true);
      void queryClient.invalidateQueries({ queryKey: ["workflow-templates"] });
    },
  });

  const uploadSourceImage = useMutation({
    mutationFn: async (file: File) => {
      const job = await ensureSaved();
      return uploadJobSourceImage(job.id, {
        filename: file.name,
        content_base64: await fileToBase64(file),
        content_type: file.type || "image/png",
      });
    },
    onMutate: async (file) => {
      setPendingSourceImageName(file.name);
      if (currentTopicId) {
        await queryClient.cancelQueries({ queryKey: ["on-demand-video", currentTopicId] });
      }
    },
    onSuccess: (updatedJob) => {
      setRenderPreflightError(null);
      setPendingSourceImageName(mediaDisplayName(updatedJob.source_image_asset));
      cacheUpdatedJob(updatedJob);
      invalidate();
    },
    onError: () => {
      setPendingSourceImageName("");
    },
  });

  const uploadAudio = useMutation({
    mutationFn: async (file: File) => {
      const job = await ensureSaved();
      return uploadJobAudio(job.id, {
        filename: file.name,
        content_base64: await fileToBase64(file),
        content_type: file.type || "audio/mpeg",
      });
    },
    onMutate: async (file) => {
      setPendingAudioFileName(file.name);
      if (currentTopicId) {
        await queryClient.cancelQueries({ queryKey: ["on-demand-video", currentTopicId] });
      }
    },
    onSuccess: (updatedJob) => {
      setRenderPreflightError(null);
      const nextDuration = applyAudioDuration(activeAudioAsset(updatedJob));
      setPendingAudioFileName(mediaDisplayName(activeAudioAsset(updatedJob)));
      cacheUpdatedJob(updatedJob);
      if (nextDuration) {
        void updateJobRenderOverrides(updatedJob.id, renderOverrides(nextDuration)).then((savedJob) => {
          setPendingAudioFileName(mediaDisplayName(activeAudioAsset(savedJob)));
          cacheUpdatedJob(savedJob);
          invalidate();
        }).catch(() => invalidate());
      } else {
        invalidate();
      }
    },
    onError: () => {
      setPendingAudioFileName("");
    },
  });

  const selectAudio = useMutation({
    mutationFn: ({ jobId, assetId }: { jobId: string; assetId: string; durationOverride?: string }) => selectJobAudio(jobId, assetId),
    onSuccess: (updatedJob, variables) => {
      const confirmedAudio = activeAudioAsset(updatedJob)
        ?? updatedJob.audio_assets?.find((asset) => asset.id === variables.assetId)
        ?? currentJob?.audio_assets?.find((asset) => asset.id === variables.assetId);
      const nextDuration = applyAudioDuration(confirmedAudio) ?? variables.durationOverride ?? null;
      pendingAudioSelectionRef.current = null;
      cacheUpdatedJob(updatedJob);
      if (nextDuration) {
        void updateJobRenderOverrides(updatedJob.id, renderOverrides(nextDuration)).then((savedJob) => {
          cacheUpdatedJob(savedJob);
          invalidate();
        }).catch(() => invalidate());
      } else {
        invalidate();
      }
    },
    onError: () => {
      pendingAudioSelectionRef.current = null;
      manualAudioSelectionRef.current = null;
      setSelectedAudioAssetId(defaultRenderAudioAsset(currentJob)?.id ?? "");
    },
  });

  function handleAudioSourceChange(assetId: string): void {
    setSelectedAudioAssetId(assetId);
    manualAudioSelectionRef.current = assetId || null;
    pendingAudioSelectionRef.current = assetId || null;
    const selectedAsset = currentJob?.audio_assets?.find((asset) => asset.id === assetId) ?? null;
    const durationOverride = applyAudioDuration(selectedAsset) ?? undefined;
    if (currentJob && assetId) selectAudio.mutate({ jobId: currentJob.id, assetId, durationOverride });
  }

  const deleteAsset = useMutation({
    mutationFn: deleteMediaAsset,
    onSuccess: invalidate,
  });

  useEffect(() => {
    if (active || !title.trim() || !renderProfileId || generateScript.isPending || generateAudio.isPending || generateVideo.isPending || uploadAudio.isPending || uploadSourceImage.isPending || importWorkflow.isPending) return;
    const input = saveInput();
    const saveKey = JSON.stringify({ topicId: currentTopicId, input });
    if (saveKey === lastAutosaveKeyRef.current) return;
    setAutosaveState("idle");
    const timeout = window.setTimeout(() => {
      lastAutosaveKeyRef.current = saveKey;
      setAutosaveState("saving");
      saveMutation.mutate(undefined, {
        onSuccess: () => setAutosaveState("saved"),
        onError: () => {
          lastAutosaveKeyRef.current = "";
          setAutosaveState("error");
        },
      });
    }, 900);
    return () => window.clearTimeout(timeout);
  }, [
    active,
    currentTopicId,
    generateAudio.isPending,
    generateScript.isPending,
    generateVideo.isPending,
    importWorkflow.isPending,
    renderProfileId,
    saveInput,
    saveMutation,
    title,
    uploadAudio.isPending,
    uploadSourceImage.isPending,
  ]);

  const selectedVoice = voices.find((voice) => voice.voice_id === voiceId);
  const scriptGenerating = generateScript.isPending || currentJob?.status === "generating_content";

  function insertVideoPromptVariable(token: string) {
    const textarea = videoPromptRef.current;
    if (!textarea) {
      setVideoPrompt((current) => `${current}${token}`);
      return;
    }
    const start = textarea.selectionStart ?? videoPrompt.length;
    const end = textarea.selectionEnd ?? start;
    const nextValue = `${videoPrompt.slice(0, start)}${token}${videoPrompt.slice(end)}`;
    setVideoPrompt(nextValue);
    window.requestAnimationFrame(() => {
      textarea.focus();
      const cursor = start + token.length;
      textarea.setSelectionRange(cursor, cursor);
    });
  }

  useEffect(() => {
    const createVideoSettings = isRecord(currentJob?.render_overrides?.create_video) ? currentJob.render_overrides.create_video : {};
    if (!voiceId && typeof createVideoSettings.voice_id !== "string" && voices[0]) setVoiceId(voices[0].voice_id);
  }, [currentJob, voices, voiceId]);

  useEffect(() => {
    if (currentJob?.speech_script && currentJob.speech_script !== syncedScriptRef.current && !generateAudio.isPending && !scriptDirtyRef.current) {
      setScript(currentJob.speech_script);
      syncedScriptRef.current = currentJob.speech_script;
    }
  }, [currentJob?.speech_script, generateAudio.isPending]);

  useEffect(() => {
    if (!awaitingAudioToastRef.current || !currentJob) return;
    if ((currentJob.audio_assets?.length ?? 0) > audioCountBeforeGenerateRef.current || (currentJob.audio_asset?.id && currentJob.audio_asset.id !== audioIdBeforeGenerateRef.current)) {
      awaitingAudioToastRef.current = false;
      const generatedAudio = latestGeneratedAudioAsset(currentJob) ?? activeAudioAsset(currentJob);
      if (generatedAudio?.id) {
        manualAudioSelectionRef.current = generatedAudio.id;
        setSelectedAudioAssetId(generatedAudio.id);
      }
      applyAudioDuration(generatedAudio);
      setToast({ message: "Audio generated.", variant: "success" });
    }
  }, [applyAudioDuration, currentJob]);

  useEffect(() => {
    const activeAudio = currentJob?.audio_assets?.find((asset) => asset.id === selectedAudioAssetId) ?? defaultRenderAudioAsset(currentJob);
    if (!activeAudio?.id || activeAudio.id === lastAppliedAudioDurationAssetIdRef.current) return;
    applyAudioDuration(activeAudio);
  }, [applyAudioDuration, currentJob, selectedAudioAssetId]);

  const error = saveMutation.error ?? generateScript.error ?? generateAudio.error ?? generateVideo.error ?? cancelRender.error ?? saveOverrides.error ?? attachVoice.error ?? selectAudio.error ?? deleteAsset.error ?? importWorkflow.error ?? uploadSourceImage.error ?? uploadAudio.error;

  return (
    <section className="create-video-workspace" aria-label="Create Video">
      <div className="create-video-hero">
        <div>
          <span className="hero-kicker">ON-DEMAND VIDEO</span>
          <h2>Create Video</h2>
          <p>Write or generate a script, create ElevenLabs audio, then render with LTX 2.3.</p>
        </div>
        <div className="create-video-save-group">
          <small className={`autosave-status ${autosaveState}`}>{autosaveState === "saving" ? "Autosaving…" : autosaveState === "saved" ? "Draft saved" : autosaveState === "error" ? "Autosave failed" : "Autosave on"}</small>
          <button className="button button-primary create-video-save" type="button" disabled={!title.trim() || !renderProfileId || saveMutation.isPending || active} onClick={() => saveMutation.mutate()}>
            {saveMutation.isPending ? "Saving…" : "Save now"}
          </button>
        </div>
      </div>

      <div className="create-video-grid">
        <section className="panel create-video-card">
          <div className="panel-heading"><div><h3>Script & voice</h3><p>{formatUsage(usage.data)}</p></div><button className="icon-button" type="button" aria-label={audioControlsOpen ? "Collapse ElevenLabs Generate Audio control" : "Expand ElevenLabs Generate Audio control"} onClick={() => setAudioControlsOpen((open) => !open)}>{audioControlsOpen ? "⌃" : "⌄"}</button></div>
          <label className="field-label">Video title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="How high achievers handle micromanagement" /></label>
          {audioControlsOpen && <div className="create-video-collapsible"><label className="field-label">Render engine<select value={renderProfileId} onChange={(event) => setRenderProfileId(event.target.value)}><option value="" disabled>Select render engine</option>{renderProfiles.filter((profile) => profile.is_active).map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
            <label className="field-label">ElevenLabs voice<select value={voiceId} onChange={(event) => setVoiceId(event.target.value)}><option value="" disabled>Select voice</option>{voices.map((voice) => <option key={voice.voice_id} value={voice.voice_id}>{voiceLabel(voice)}</option>)}</select></label>
            {selectedVoice?.preview_url && <audio controls preload="none" src={selectedVoice.preview_url}>Your browser does not support audio playback.</audio>}
            <div className="create-video-voice-controls" aria-label="ElevenLabs parameters">
              <label className="voice-slider"><span className="control-label-with-tooltip">Speed <InfoTooltip label="Controls speaking speed. Lower is slower; higher is faster." /></span><span>{voiceSpeed}</span><input type="range" min="0.7" max="1.2" step="0.01" value={voiceSpeed} onChange={(event) => setVoiceSpeed(event.target.value)} /></label>
              <label className="voice-slider"><span className="control-label-with-tooltip">Stability <InfoTooltip label="Controls voice consistency. Lower allows more variation; higher is steadier." /></span><span>{voiceStability}%</span><input type="range" min="0" max="100" step="1" value={voiceStability} onChange={(event) => setVoiceStability(event.target.value)} /></label>
              <label className="voice-slider"><span className="control-label-with-tooltip">Similarity <InfoTooltip label="Controls how closely the output matches the selected voice." /></span><span>{voiceSimilarity}%</span><input type="range" min="0" max="100" step="1" value={voiceSimilarity} onChange={(event) => setVoiceSimilarity(event.target.value)} /></label>
              <label className="voice-slider"><span className="control-label-with-tooltip">Style exaggeration <InfoTooltip label="Controls expressiveness. Higher values make delivery more dramatic." /></span><span>{voiceStyle}%</span><input type="range" min="0" max="100" step="1" value={voiceStyle} onChange={(event) => setVoiceStyle(event.target.value)} /></label>
              <label className="field-label"><span className="control-label-with-tooltip">Output format <InfoTooltip label="Controls audio file type and bitrate for generated speech." /></span><select value={voiceOutputFormat} onChange={(event) => setVoiceOutputFormat(event.target.value)}><option value="mp3_44100_128">MP3 44.1 kHz (128kbps)</option><option value="mp3_44100_192">MP3 44.1 kHz (192kbps)</option><option value="wav_44100">WAV 44.1 kHz</option></select></label>
              <label className="eleven-toggle-row"><span><strong className="control-label-with-tooltip">Speaker boost <InfoTooltip label="Boosts similarity to the original speaker, sometimes at the cost of variation." /></strong><small>Increase similarity to the original speaker.</small></span><button className={`switch-control${voiceSpeakerBoost ? " active" : ""}`} type="button" role="switch" aria-checked={voiceSpeakerBoost} onClick={() => setVoiceSpeakerBoost((enabled) => !enabled)}><span /></button></label>
            </div>
            <label className="field-label">Audio Script<textarea rows={10} value={script} onInput={(event) => { scriptDirtyRef.current = true; setScript(event.currentTarget.value); }} onChange={(event) => { scriptDirtyRef.current = true; setScript(event.target.value); }} placeholder="Paste the exact words the avatar should speak." /></label>
            <div className="create-video-actions">
              <button className="button button-secondary button-with-spinner" type="button" disabled={scriptGenerating || !title.trim() || !renderProfileId || active} onClick={() => generateScript.mutate()}>{scriptGenerating && <span className="inline-spinner" aria-hidden="true" />}{scriptGenerating ? "LLM generating audio script…" : "Generate script with AI"}</button>
              <button className="button button-primary button-with-spinner" type="button" disabled={generateAudio.isPending || !script.trim() || !voiceId || active} onClick={() => generateAudio.mutate()}>{generateAudio.isPending && <span className="inline-spinner" aria-hidden="true" />}{generateAudio.isPending ? "Generating audio…" : "Generate Audio"}</button>
            </div>{scriptGenerating && <p className="create-video-inline-status" role="status">LLM is writing the audio script. This can take a few seconds.</p>}</div>}
        </section>

        <section className="panel create-video-card">
          <div className="panel-heading"><div><h3>Generated audio</h3><p>Select the audio used for the next render.</p></div></div>
          {currentJob?.audio_assets?.length ? <div className="create-video-audio-list">{currentJob.audio_assets.map((asset) => <article className={`create-video-audio${asset.kind === "audio" ? " active" : ""}`} key={asset.id}><div className="create-video-media-title"><div><strong>{asset.filename}</strong><small>{asset.kind === "audio" ? "Active render audio" : "Saved audio"}</small></div></div><audio controls preload="none" src={`${asset.download_url}?inline=true`}>Your browser does not support audio playback.</audio><button className="job-media-icon" type="button" aria-label={asset.kind === "audio" ? `Using ${asset.filename}` : `Use ${asset.filename}`} title={asset.kind === "audio" ? "Using audio" : "Use audio"} disabled={asset.kind === "audio" || selectAudio.isPending || active} onClick={() => handleAudioSourceChange(asset.id)}><svg viewBox="0 0 24 24" aria-hidden="true">{asset.kind === "audio" ? <path d="M5 13l4 4L19 7" /> : <path d="M5 12h13m0 0-5-5m5 5-5 5" />}</svg></button><button className="job-media-icon danger" type="button" aria-label={`Delete ${asset.filename}`} title="Delete audio" disabled={deleteAsset.isPending || active} onClick={() => deleteAsset.mutate(asset.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg></button></article>)}</div> : <p className="field-hint">Generated audio will appear here.</p>}
        </section>

        <section className="panel create-video-card create-video-ltx">
          <div className="panel-heading"><div><h3>LTX 2.3 controls</h3><p>{firstProfile ? `Using ${firstProfile.name}` : "Choose a render profile"}</p></div></div>
          <div className="create-video-workflow-row">
            <label className="field-label">Base workflow<select value={workflowTemplateId} onChange={(event) => { const id = event.target.value; setWorkflowTemplateId(id); const workflow = workflowTemplates.find((item) => item.id === id); if (workflow) applyWorkflowBase(workflow); }}><option value="">Use render engine default</option>{workflowTemplates.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</select></label>
          </div>
          <div className="create-video-override-group">
            <div className="create-video-override-heading"><div><strong>Workflow overrides</strong><small>Override the base workflow JSON, source image, or audio for this video only.</small></div></div>
            <div className="create-video-media-pickers">
              <div className="create-video-override-item">
                <span className="create-video-override-label">Workflow JSON</span>
                <label className="create-video-file-control"><input type="file" accept="application/json,.json" disabled={importWorkflow.isPending || active} onChange={(event) => { const file = event.target.files?.[0]; if (file) importWorkflow.mutate(file); event.target.value = ""; }} /><span>{importWorkflow.isPending ? "Importing…" : "Choose JSON"}</span></label>
                <small className="field-hint">Optional. Use a different API workflow as this video’s base.</small>
              </div>
              <div className="create-video-override-item">
                <span className="create-video-override-label">Source image</span>
                <label className="create-video-file-control"><input type="file" accept="image/*" disabled={uploadSourceImage.isPending || active || !title.trim() || !renderProfileId} onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadSourceImage.mutate(file); event.target.value = ""; }} /><span>{uploadSourceImage.isPending ? "Uploading image…" : "Source image"}</span></label>
                <small className="field-hint">{sourceImageDisplayName ? `Override image: ${sourceImageDisplayName}` : "Using workflow default image until overridden."}</small>
              </div>
              <div className="create-video-override-item">
                <span className="create-video-override-label">Audio file</span>
                <label className="create-video-file-control"><input type="file" accept="audio/*" disabled={uploadAudio.isPending || active || !title.trim() || !renderProfileId} onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadAudio.mutate(file); event.target.value = ""; }} /><span>{uploadAudio.isPending ? "Uploading audio…" : "Audio file"}</span></label>
                <small className="field-hint">{audioFileDisplayName ? `Override audio: ${audioFileDisplayName}` : "Using workflow default audio until overridden."}</small>
              </div>
            </div>
            <label className="field-label">Audio source<select value={selectedAudioAssetId} disabled={!currentJob?.audio_assets?.length || selectAudio.isPending || active} onChange={(event) => handleAudioSourceChange(event.target.value)}><option value="">No generated audio selected</option>{currentJob?.audio_assets?.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}{asset.kind === "audio" ? " · active" : ""}</option>)}</select></label>
          </div>
          <label className="field-label">Video prompt<textarea ref={videoPromptRef} rows={7} value={videoPrompt} onChange={(event) => setVideoPrompt(event.target.value)} placeholder="Describe the visual style and movement for LTX 2.3." /></label>
          <div className="prompt-template-vars create-video-vars"><small>Supported variable</small><button className="prompt-var" type="button" onClick={() => insertVideoPromptVariable("{{SCRIPT}}")}>{"{{SCRIPT}}"}</button><small>Expands to Audio Script when rendering.</small></div>
          <div className="ltx-control-row">
            <label className="field-label">FPS<input inputMode="numeric" value={fps} onChange={(event) => setFps(event.target.value)} /></label>
            <label className="field-label">Duration<input inputMode="numeric" value={duration} onChange={(event) => setDuration(event.target.value)} /></label>
            <label className="field-label">Seed<input inputMode="numeric" value={seed} onChange={(event) => setSeed(event.target.value)} placeholder="Workflow default" /></label>
          </div>
          <div className="create-video-actions">
            <button className="button button-secondary" type="button" disabled={saveOverrides.isPending || !currentJob || active} onClick={() => saveOverrides.mutate()}>{saveOverrides.isPending ? "Saving controls…" : "Save LTX controls"}</button>
            <button className="button button-primary create-video-generate" type="button" disabled={generateVideo.isPending || selectAudio.isPending || !renderProfileId || active} onClick={handleGenerateVideo}>{generateVideo.isPending ? "Queuing video…" : "Generate Video"}</button>
            <button className="button button-secondary rendered-settings-action" type="button" disabled={!currentRenderedControls.length} onClick={() => setRenderedLtxParams(currentRenderedControls)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10m4 0h2M4 17h2m4 0h10M14 4v6M6 14v6" /></svg>Rendered LTX params</button>
          </div>
          {(!currentJob?.source_image_asset || !currentJob?.audio_asset) && <p className="field-hint">Source image and audio are required before rendering video.</p>}
          {latestAttempt && <div className="create-video-progress"><span>{renderProgress(latestAttempt)} <RenderElapsed attempt={latestAttempt} nowMs={renderNowMs} /></span><progress max={100} value={latestAttempt.progress > 1 ? latestAttempt.progress : undefined} />{CANCELABLE_RENDER_STATUSES.has(latestAttempt.status) && <button className="job-media-icon danger" type="button" aria-label="Cancel rendering" title="Cancel rendering" disabled={cancelRender.isPending} onClick={() => cancelRender.mutate(latestAttempt.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg></button>}</div>}
        </section>

        <section className="panel create-video-card">
          <div className="panel-heading"><div><h3>Completed video history</h3><p>Completed renders for this created video.</p></div></div>
          {jobAttempts.length ? <div className="create-video-video-list">{jobAttempts.map((attempt) => <article className="create-video-render" key={attempt.id}><div><div><strong>{attempt.output_filename ?? `${attempt.provider} render`}</strong><small>{renderProgress(attempt)} · <RenderElapsed attempt={attempt} /> · <HumanDate value={attempt.updated_at} /></small></div><button className="job-media-icon" type="button" aria-label={`Show rendered LTX params for ${attempt.output_filename ?? attempt.id}`} title="Rendered LTX params" onClick={() => setRenderedLtxParams(attempt.rendered_controls)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10m4 0h2M4 17h2m4 0h10M14 4v6M6 14v6" /></svg></button></div>{attempt.assets.length ? attempt.assets.map((asset) => <div className="create-video-video" key={asset.id}><video controls preload="metadata" src={`${asset.download_url}?inline=true`}>Your browser does not support video playback.</video><div className="create-video-video-actions"><a className="job-media-icon" href={asset.download_url} download={asset.filename} aria-label={`Download ${asset.filename}`} title="Download video"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M5 21h14" /></svg></a><button className="job-media-icon danger" type="button" aria-label={`Delete ${asset.filename}`} title="Delete video" disabled={deleteAsset.isPending || attempt.status !== "completed"} onClick={() => deleteAsset.mutate(asset.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg></button></div></div>) : <p className="field-hint">{attempt.output_deleted_at ? "Deleted" : "No output file yet."}</p>}</article>)}</div> : <p className="field-hint">Generated videos will appear here.</p>}
        </section>
      </div>

      {error && <p className="form-error" role="alert">{error.message}</p>}
      {renderPreflightError && <p className="form-error" role="alert">{renderPreflightError}</p>}
      {active && <p className="field-hint">This created video is active. Editing is locked until the current generation step finishes.</p>}
      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
      <RenderedLtxParamsDialog controls={renderedLtxParams} onClose={() => setRenderedLtxParams(null)} />
    </section>
  );
}

export function CreatedVideosSidebar() {
  const videos = useQuery({ queryKey: ["on-demand-videos", "sidebar"], queryFn: () => getOnDemandVideos(5, 0), refetchInterval: 5000 });
  const createdVideos = videos.data?.items ?? [];

  return (
    <div className="created-video-sidebar">
      <div className="created-video-sidebar-heading"><span>Created Videos</span><a href="/created-videos">View all</a></div>
      {videos.isLoading && <small>Loading…</small>}
      {videos.isError && <small>Created videos unavailable.</small>}
      {!videos.isLoading && !videos.isError && createdVideos.length === 0 && <small>No created videos yet.</small>}
      {createdVideos.map((video) => <div className="created-video-sidebar-item compact" key={video.id}><a href={`/created-videos?video=${video.id}`}><strong>{video.name}</strong><small>{video.status} · <HumanDate value={video.updated_at} /></small></a></div>)}
      <a className="created-video-sidebar-new" href="/#create-video">+ New video</a>
    </div>
  );
}

export function CreatedVideosPage() {
  const queryClient = useQueryClient();
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null);
  const videos = useQuery({ queryKey: ["on-demand-videos", "full"], queryFn: () => getOnDemandVideos(100, 0), refetchInterval: 5000 });
  const cloneMutation = useMutation({
    mutationFn: cloneOnDemandVideo,
    onSuccess: (topic) => {
      setSelectedTopicId(topic.id);
      void queryClient.invalidateQueries({ queryKey: ["on-demand-videos"] });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: deleteTopic,
    onSuccess: () => {
      setSelectedTopicId(null);
      void queryClient.invalidateQueries({ queryKey: ["on-demand-videos"] });
    },
  });
  const [pendingDelete, setPendingDelete] = useState<TopicSummary | null>(null);
  const createdVideos = useMemo(() => videos.data?.items ?? [], [videos.data?.items]);
  const selectedVideo = createdVideos.find((video) => video.id === selectedTopicId) ?? null;

  useEffect(() => {
    if (selectedTopicId || createdVideos.length === 0) return;
    const params = new URLSearchParams(window.location.search);
    const urlVideoId = params.get("video");
    setSelectedTopicId(createdVideos.some((video) => video.id === urlVideoId) ? urlVideoId : createdVideos[0].id);
  }, [createdVideos, selectedTopicId]);

  return (
    <section className="created-videos-page" aria-label="Created videos">
      <aside className="created-videos-list panel">
        <div className="panel-heading"><div><h2>Created videos</h2><p>Open a saved on-demand video to edit and render.</p></div><a className="button button-secondary button-small" href="/#create-video">New</a></div>
        {videos.isLoading && <p className="field-hint">Loading created videos…</p>}
        {videos.isError && <p className="form-error">Created videos unavailable.</p>}
        {!videos.isLoading && !videos.isError && createdVideos.length === 0 && <p className="field-hint">No created videos yet.</p>}
        <div className="created-videos-list-items">
          {createdVideos.map((video) => <article className={`created-videos-list-item${video.id === selectedTopicId ? " active" : ""}`} key={video.id}><button type="button" onClick={() => setSelectedTopicId(video.id)}><strong>{video.name}</strong><small>{video.status} · {video.content_count} item · <HumanDate value={video.updated_at} /></small></button><button className="job-media-icon" type="button" aria-label={`Clone ${video.name}`} title="Clone" disabled={cloneMutation.isPending} onClick={() => cloneMutation.mutate(video.id)}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg></button><button className="job-media-icon danger" type="button" aria-label={`Delete ${video.name}`} title="Delete" disabled={deleteMutation.isPending} onClick={() => setPendingDelete(video)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg></button></article>)}
        </div>
      </aside>
      <div className="created-videos-editor">
        {selectedTopicId ? <CreateVideoPanel topicId={selectedTopicId} onSaved={setSelectedTopicId} /> : <section className="panel empty-editor"><h2>Select a created video</h2><p>Choose a saved video from the list to edit it here.</p></section>}
        {selectedVideo && <p className="field-hint">Editing: {selectedVideo.name}</p>}
      </div>
      {pendingDelete && <div className="modal-backdrop" role="presentation"><section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-created-video-title"><h2 id="delete-created-video-title">Delete created video?</h2><p>“{pendingDelete.name}” and all generated audio/video files will be permanently deleted.</p><div className="confirm-actions"><button className="button button-secondary" type="button" onClick={() => setPendingDelete(null)}>Cancel</button><button className="button button-danger" type="button" onClick={() => { deleteMutation.mutate(pendingDelete.id); setPendingDelete(null); }}>Delete</button></div></section></div>}
    </section>
  );
}
