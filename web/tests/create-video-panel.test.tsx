import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "../app/providers";
import { CreatedVideosPage, CreatedVideosSidebar, CreateVideoPanel } from "../components/create-video-panel";

const renderProfile = {
  id: "profile-1",
  name: "Elena LTX",
  character_id: "character-1",
  voice_profile_id: "voice-profile-1",
  renderer_provider: "comfyui",
  workflow_template_id: "workflow-1",
  is_active: true,
  created_at: "2026-08-10T00:00:00Z",
  updated_at: "2026-08-10T00:00:00Z",
};

function job(overrides: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    batch_id: "topic-1",
    topic: "Created video",
    content_number: 1,
    status: "content_ready",
    render_profile_id: "profile-1",
    voice_profile_id: "voice-profile-1",
    workflow_template_id: "workflow-1",
    target_duration_seconds: 30,
    error_message: null,
    speech_script: "Saved script",
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
    render_overrides: overrides,
    audio_asset: null,
    audio_assets: [],
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
  };
}

function topic(overrides: Record<string, unknown> = {}) {
  return {
    id: "topic-1",
    name: "Created video",
    status: "draft",
    default_render_profile_id: "profile-1",
    target_duration_seconds: 30,
    auto_fit_duration: false,
    creation_mode: "created_video",
    content_count: 1,
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
    contents: [job(overrides)],
  };
}

describe("CreateVideoPanel", () => {
  it("saves an independently uploaded second image and its enabled state", async () => {
    const requests: Array<{ url: string; body?: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, body: init?.body ? String(init.body) : undefined });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/workflow-templates")) return json({ items: [{ ...workflowTemplate(), name: "MiniMax H3", workflow_json: { ...workflowTemplate().workflow_json, size: { class_type: "ResolutionSelector", inputs: { aspect_ratio: "9:16 (Portrait Widescreen)", megapixels: 0.5, multiple: 32 } }, generator: { class_type: "MiniMaxH3ReferenceToVideo", inputs: { width: ["size", 0], height: ["size", 1] } } }, metadata_json: { optional_image_references: [{ key: "second_image", label: "Second image reference", enabled: false, asset_key: "workflow-media/original.png" }] } }], total: 1 });
      if (url.includes("/workflow-media")) return json({ asset_key: "workflow-media/new-reference.png", filename: "new-reference.png", input_type: "image" }, 201);
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [], total: 0 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ configured: false });
      if (url.includes("/render-nodes") || url.includes("/render-attempts")) return json({ items: [], total: 0 });
      if (url.includes("/on-demand-videos")) return json({ items: [], total: 0 });
      return json(topic());
    });
    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);
    const toggle = await screen.findByRole("checkbox", { name: "Enable second image reference" });
    expect(toggle).not.toBeChecked();
    expect(screen.getByRole("heading", { name: "Workflow: MiniMax H3" })).toBeInTheDocument();
    expect(screen.getByLabelText("Image megapixels")).toHaveValue(0.5);
    expect(screen.getByLabelText("Size multiple")).toHaveValue(32);
    fireEvent.change(screen.getByLabelText("Image megapixels"), { target: { value: "1.25" } });
    fireEvent.change(screen.getByLabelText("Aspect ratio"), { target: { value: "16:9 (Widescreen)" } });
    fireEvent.change(screen.getByLabelText("Second source image"), { target: { files: [new File(["second image"], "new-reference.png", { type: "image/png" })] } });
    await waitFor(() => expect(toggle).toBeChecked());
    expect(screen.getByText(/new-reference.png · Enabled/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save LTX controls" }));
    await waitFor(() => expect(requests.some((request) => request.body?.includes('"second_image_asset":"workflow-media/new-reference.png"') && request.body.includes('"second_image":true'))).toBe(true));
    expect(requests.some((request) => request.body?.includes('"image_megapixels":1.25') && request.body.includes('"image_aspect_ratio":"16:9 (Widescreen)"'))).toBe(true);
    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
  });

  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("autosaves a created video draft without using topic/content history", async () => {
    const requests: Array<{ url: string; body?: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, body: init?.body ? String(init.body) : undefined });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }, { voice_id: "voice-rachel", name: "Rachel", category: "saved", description: null, preview_url: null }], total: 2 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      if (url.endsWith("/api/v1/on-demand-videos") && init?.method === "POST") return json(topic(), 201);
      if (url.includes("/on-demand-videos")) return json({ items: [], total: 0, limit: 50, offset: 0 });
      return json(topic());
    });

    const { container } = render(<Providers><CreateVideoPanel /></Providers>);
    const panel = within(container);

    fireEvent.change(await panel.findByLabelText("Video title"), { target: { value: "Created video" } });
    fireEvent.change(await panel.findByLabelText("ElevenLabs voice"), { target: { value: "voice-rachel" } });
    fireEvent.change(panel.getByLabelText("ElevenLabs model"), { target: { value: "eleven_v4" } });
    fireEvent.change(panel.getByLabelText("Audio Script"), { target: { value: "Manual script" } });
    fireEvent.change(panel.getByLabelText("Video prompt"), { target: { value: "A modern creator speaks" } });

    await waitFor(() => expect(requests.some((request) => request.url.endsWith("/api/v1/on-demand-videos") && request.body?.includes("A modern creator speaks"))).toBe(true), { timeout: 2000 });
    expect(requests.some((request) => request.url.endsWith("/api/v1/on-demand-videos") && request.body?.includes('"voice_id":"voice-rachel"'))).toBe(true);
    expect(requests.some((request) => request.body?.includes('"voice_model":"eleven_v4"'))).toBe(true);
    expect(await panel.findByText("Draft saved")).toBeInTheDocument();
    expect(requests.some((request) => request.url.includes("/api/v1/topics") && request.body)).toBe(false);
  });

  it("loads the last Create Video settings for a new created video", async () => {
    window.localStorage.setItem("ugc-create-video-last-settings-v1", JSON.stringify({
      render_profile_id: "profile-1",
      workflow_template_id: "workflow-1",
      voice_id: "voice-hope",
      video_prompt: "Remembered LTX prompt",
      fps: "30",
      duration: "45",
      seed: "777",
      audio_controls_open: true,
      voice_speed: "1.08",
      voice_model: "eleven_v4",
      voice_stability: "33",
      voice_similarity: "66",
      voice_style: "44",
      voice_output_format: "mp3_44100_192",
      voice_speaker_boost: false,
    }));
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/workflow-templates")) return json({ items: [workflowTemplate()], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      if (url.includes("/on-demand-videos")) return json({ items: [], total: 0, limit: 50, offset: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel /></Providers>);

    expect(await screen.findByDisplayValue("Remembered LTX prompt")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Render engine")).toHaveValue("profile-1"));
    await waitFor(() => expect(screen.getByLabelText("Base workflow")).toHaveValue("workflow-1"));
    await waitFor(() => expect(screen.getByLabelText("ElevenLabs voice")).toHaveValue("voice-hope"));
    expect(screen.getByLabelText("FPS")).toHaveValue("30");
    expect(screen.getByLabelText("Duration")).toHaveValue("45");
    expect(screen.getByLabelText("Seed")).toHaveValue("777");
    expect(screen.getByLabelText(/Output format/)).toHaveValue("mp3_44100_192");
    expect(screen.getByLabelText("ElevenLabs model")).toHaveValue("eleven_v4");
    expect(screen.queryByLabelText(/Speed/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Stability/)).toHaveValue("33");
    expect(screen.getByLabelText(/Similarity/)).toHaveValue("66");
    expect(screen.queryByLabelText(/Style exaggeration/)).not.toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: /Speaker boost/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("ElevenLabs model"), { target: { value: "eleven_multilingual_v2" } });
    expect(screen.getByLabelText(/Speed/)).toHaveValue("1.08");
    expect(screen.getByLabelText(/Style exaggeration/)).toHaveValue("44");
    expect(screen.getByText("Workflow overrides")).toBeInTheDocument();
    expect(screen.getByText("Override the base workflow JSON, source image, or audio for this video only.")).toBeInTheDocument();
    expect(screen.queryByText("Pick source image")).not.toBeInTheDocument();
    expect(screen.queryByText("Pick audio file")).not.toBeInTheDocument();
  });

  it("keeps an in-progress prompt and its caret when an older autosave returns", async () => {
    let savedPrompt = "Elena speaks";
    let completeFirstSave: (() => void) | undefined;
    let serverReads = 0;
    const writes: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/on-demand-videos/topic-1") || url.endsWith("/topics/topic-1")) {
        if (init?.method === "PUT") {
          const nextPrompt: string = JSON.parse(String(init.body)).render_overrides.video_prompt;
          writes.push(nextPrompt);
          if (writes.length === 1) {
            await new Promise<void>((resolve) => { completeFirstSave = resolve; });
          }
          savedPrompt = nextPrompt;
        } else {
          serverReads += 1;
        }
        return json(topic({ video_prompt: savedPrompt }));
      }
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      return json({ items: [], total: 0 });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);
    const prompt = await screen.findByDisplayValue<HTMLTextAreaElement>("Elena speaks");
    fireEvent.change(prompt, { target: { value: "Elena speaks softly" } });
    await waitFor(() => expect(completeFirstSave).toBeDefined(), { timeout: 2000 });

    prompt.focus();
    fireEvent.change(prompt, { target: { value: "Elena now speaks softly " } });
    prompt.setSelectionRange(9, 9);
    const readsBeforeSave = serverReads;
    completeFirstSave?.();

    await waitFor(() => expect(serverReads).toBeGreaterThan(readsBeforeSave));
    expect(prompt).toHaveValue("Elena now speaks softly ");
    expect(prompt.selectionStart).toBe(9);
    expect(prompt.selectionEnd).toBe(9);
    await waitFor(() => expect(writes).toEqual(["Elena speaks softly", "Elena now speaks softly"]), { timeout: 2000 });
  });

  it("inserts the SCRIPT variable into the video prompt", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      if (url.includes("/on-demand-videos")) return json({ items: [], total: 0, limit: 50, offset: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel /></Providers>);

    const prompt = await screen.findByLabelText("Video prompt");
    fireEvent.change(prompt, { target: { value: "Elena says: " } });
    fireEvent.click(screen.getByRole("button", { name: "{{SCRIPT}}" }));

    expect(prompt).toHaveValue("Elena says: {{SCRIPT}}");
  });

  it("shows five recent created videos in the sidebar and links to the full page", async () => {
    const items = Array.from({ length: 6 }, (_, index) => ({ ...topic(), id: `topic-${index + 1}`, name: `Created video ${index + 1}`, contents: undefined }));
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/on-demand-videos")) return json({ items: items.slice(0, 5), total: 6, limit: 5, offset: 0 });
      return json({});
    });

    render(<Providers><CreatedVideosSidebar /></Providers>);

    expect(await screen.findByRole("link", { name: /Created video 1/i })).toHaveAttribute("href", "/created-videos?video=topic-1");
    expect(screen.queryByText("Created video 6")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View all" })).toHaveAttribute("href", "/created-videos");
  });

  it("loads clicked created video into the full page editor", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/on-demand-videos")) return json({ items: [{ ...topic(), contents: undefined }], total: 1, limit: 12, offset: 0 });
      if (url.includes("/topics/topic-1")) return json(topic({ video_prompt: "Saved prompt" }));
      if (url.includes("/on-demand-videos/topic-1")) return json(topic({ video_prompt: "Saved prompt" }));
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      return json({});
    });

    render(<Providers><CreatedVideosPage /></Providers>);

    const buttons = await screen.findAllByRole("button", { name: /Created video/i });
    fireEvent.click(buttons[0]);
    expect(await screen.findByDisplayValue("Saved prompt")).toBeInTheDocument();
  });

  it("keeps the generated audio script editable with manual newlines", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/topics/topic-1")) return json(topic({ video_prompt: "Saved prompt" }));
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const script = await screen.findByLabelText("Audio Script");
    await waitFor(() => expect(script).toHaveValue("Saved script"));
    fireEvent.input(script, { target: { value: "Saved script\n\nManual new paragraph" } });

    await waitFor(() => expect(script).toHaveValue("Saved script\n\nManual new paragraph"));
  });

  it("shows LLM script generation progress while content is running", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/topics/topic-1")) return json({ ...topic(), contents: [{ ...job(), status: "generating_content", speech_script: null }] });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    expect(await screen.findByRole("button", { name: "LLM generating audio script…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("LLM is writing the audio script");
  });

  it("shows a notification when generated audio is available", async () => {
    const audioAsset = mediaAsset("audio-1", "audio", "created-video_content1_0001-audio.mp3");
    let speechRequested = false;
    let attachedModel: string | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/topics/topic-1")) return json({ ...topic(), contents: [{ ...job(), audio_asset: speechRequested ? audioAsset : null, audio_assets: speechRequested ? [audioAsset] : [] }] });
      if (url.includes("/on-demand-videos/topic-1")) return json(topic());
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      if (url.includes("/elevenlabs-voice")) {
        attachedModel = JSON.parse(String(init?.body)).model;
        return json(job());
      }
      if (url.includes("/script")) return json(job());
      if (url.includes("/generate-tts") && init?.method === "POST") {
        speechRequested = true;
        return json({ ...job(), status: "generating_tts" });
      }
      return json({});
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const generateAudioButton = await screen.findByRole("button", { name: "Generate Audio" });
    await waitFor(() => expect(generateAudioButton).toBeEnabled());
    fireEvent.change(screen.getByLabelText("ElevenLabs model"), { target: { value: "eleven_v3" } });
    fireEvent.click(generateAudioButton);

    expect(await screen.findByText("Audio generated.")).toBeInTheDocument();
    expect(attachedModel).toBe("eleven_v3");
  });

  it("generates replacement audio during a render and locks audio deletion", async () => {
    const audio = mediaAsset("audio-1", "audio", "original.mp3");
    const currentJob = { ...job(), status: "rendering", audio_asset: audio, audio_assets: [audio] };
    const requests: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method) requests.push(`${init.method} ${url}`);
      if (url.includes("/topics/topic-1")) return json({ ...topic(), contents: [currentJob] });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile] });
      if (url.includes("/elevenlabs/voices")) return json({ items: [{ voice_id: "hope", name: "Hope" }] });
      if (url.includes("/generate-tts")) return json({ ...currentJob, status: "generating_tts" });
      if (url.includes("/elevenlabs-voice") || url.includes("/script")) return json(currentJob);
      return json({ items: [] });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);
    const generate = await screen.findByRole("button", { name: "Generate Audio" });
    await waitFor(() => expect(generate).toBeEnabled());
    expect(screen.getByRole("button", { name: "Delete original.mp3" })).toBeDisabled();
    const player = screen.getByText("Your browser does not support audio playback.");
    expect(player).toHaveAttribute("preload", "metadata");
    Object.defineProperty(player, "duration", { value: 8.2 });
    fireEvent.loadedMetadata(player);
    expect(screen.getByLabelText("Audio length 8.2 s")).toBeVisible();
    fireEvent.click(generate);
    await waitFor(() => expect(requests.some((request) => request.endsWith("/generate-tts"))).toBe(true));
    expect(requests.some((request) => request.startsWith("PUT") && request.includes("/on-demand-videos"))).toBe(false);
  });

  it.each([false, true])("notifies asynchronous audio failures and repeated retries (existing failure: %s)", async (initialFailure) => {
    const message = "ElevenLabs speech generation failed (403). Try MP3 128kbps.";
    const existingAudio = mediaAsset("old-audio", "audio", "previous.mp3");
    let failed = initialFailure;
    const current = () => ({ ...job(), status: failed ? "failed" : "content_ready", error_message: failed ? message : null, audio_asset: existingAudio, audio_assets: [existingAudio] });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/topics/topic-1") || url.includes("/on-demand-videos/topic-1")) return json({ ...topic(), contents: [current()] });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ configured: true, remaining_units: 100, unit: "characters" });
      if (url.includes("/generate-tts") && init?.method === "POST") {
        failed = true;
        return json({ ...current(), status: "generating_tts", error_message: null });
      }
      if (url.includes("/elevenlabs-voice") || url.includes("/script")) return json(current());
      return json({ items: [], total: 0 });
    });
    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);
    if (initialFailure) {
      expect(await screen.findByRole("alert")).toHaveTextContent(message);
      fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    }
    const generate = await screen.findByRole("button", { name: "Generate Audio" });
    await waitFor(() => expect(generate).toBeEnabled());
    fireEvent.click(generate);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText("Audio generated.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
  });

  it("shows the render error separately from a replacement audio failure", async () => {
    const audioError = "ElevenLabs could not generate replacement audio";
    const renderError = "ComfyUI ran out of GPU memory";
    const attempt = renderAttempt(mediaAsset("video-1", "video", "done.mp4"), {
      status: "failed", error_message: renderError, output_filename: null, assets: [],
    });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/topics/topic-1")) {
        return json({ ...topic(), contents: [{ ...job(), status: "failed", error_message: audioError }] });
      }
      if (url.includes("/render-attempts")) return json({ items: [attempt] });
      return json({ items: [] });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);
    const renderFailure = await screen.findByText(renderError);
    const historyEntry = renderFailure.closest("article");
    expect(historyEntry).toBeInTheDocument();
    expect(historyEntry).toHaveTextContent("failed");
    expect(within(historyEntry as HTMLElement).queryByText(audioError)).toBeNull();
    expect(screen.getAllByText(audioError).length).toBeGreaterThan(0);
  });

  it("offers downloads for generated audio and shows delete icons for audio and completed videos", async () => {
    const audioAsset = mediaAsset("audio-1", "audio", "created-video_content1_0001-audio.mp3");
    const archivedAudioAsset = mediaAsset("audio-2", "audio_archive", "created-video_content1_0000-audio.mp3");
    const videoAsset = mediaAsset("video-1", "video", "created-video_content1_0001-video.mp4");
    const requests: Array<{ url: string; method?: string }> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, method: init?.method });
      if (url.includes("/topics/topic-1")) {
        return json({ ...topic(), contents: [{ ...job(), audio_asset: audioAsset, audio_assets: [audioAsset, archivedAudioAsset] }] });
      }
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [renderAttempt(videoAsset)], total: 1 });
      if (url.endsWith("/api/v1/assets/audio-1") && init?.method === "DELETE") return json({});
      return json({ items: [], total: 0, limit: 50, offset: 0 });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    expect(await screen.findByRole("button", { name: "Using created-video_content1_0001-audio.mp3" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Use created-video_content1_0000-audio.mp3" })).toBeEnabled();
    for (const asset of [audioAsset, archivedAudioAsset]) {
      const download = screen.getByRole("link", { name: `Download ${asset.filename}` });
      expect(download).toHaveAttribute("href", asset.download_url);
      expect(download).toHaveAttribute("download", asset.filename);
    }
    const deleteVideoButton = await screen.findByRole("button", { name: "Delete created-video_content1_0001-video.mp4" });
    expect(deleteVideoButton.closest("article")).toHaveTextContent("elapsed 1m 30s");
    fireEvent.click(await screen.findByRole("button", { name: "Delete created-video_content1_0001-audio.mp3" }));

    await waitFor(() => expect(requests).toContainEqual({ url: "/api/v1/assets/audio-1", method: "DELETE" }));
    expect(deleteVideoButton).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show rendered LTX params for created-video_content1_0001-video.mp4" }));
    const paramsDialog = screen.getByRole("dialog", { name: "Rendered LTX 2.3 params" });
    expect(within(paramsDialog).getByText("Image source")).toBeVisible();
    expect(within(paramsDialog).getByText("attempt-image.png")).toBeVisible();
    expect(within(paramsDialog).getByText("attempt-audio.mp3")).toBeVisible();
    expect(within(paramsDialog).getByText("Elena says: Saved script")).toBeVisible();
    expect(within(paramsDialog).queryByText("{{SCRIPT}}")).not.toBeInTheDocument();
    expect(within(paramsDialog).getByText("Seed")).toBeVisible();
    expect(within(paramsDialog).getByText("987654")).toBeVisible();
    fireEvent.click(within(paramsDialog).getByRole("button", { name: "Close rendered LTX params" }));
  });

  it("hides deleted video render history in Create Video", async () => {
    const audioAsset = mediaAsset("audio-1", "audio", "created-video_content1_0001-audio.mp3");
    const deletedVideoAsset = mediaAsset("video-deleted", "video", "deleted-video.mp4");

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/topics/topic-1")) {
        return json({ ...topic(), contents: [{ ...job(), audio_asset: audioAsset, audio_assets: [audioAsset] }] });
      }
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [renderAttempt(deletedVideoAsset, { output_deleted_at: "2026-08-10T00:02:00Z", assets: [] })], total: 1 });
      return json({ items: [], total: 0, limit: 50, offset: 0 });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    expect(await screen.findByText("Generated videos will appear here.")).toBeInTheDocument();
    expect(screen.queryByText("deleted-video.mp4")).not.toBeInTheDocument();
    expect(screen.queryByText("Deleted")).not.toBeInTheDocument();
  });

  it("deletes failed renders individually and in bulk", async () => {
    const asset = mediaAsset("video-1", "video", "completed.mp4");
    let history = [
      renderAttempt(asset, { id: "failed-1", status: "failed", assets: [], output_filename: null }),
      renderAttempt(asset, { id: "failed-2", status: "failed", assets: [], output_filename: null }),
      renderAttempt(asset),
    ];
    const requests: string[] = [];
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/topics/topic-1")) return json(topic());
      if (url.includes("/jobs/job-1/failed-render-attempts") && init?.method === "DELETE") {
        requests.push(url);
        const attemptId = url.split("attempt_id=")[1];
        history = history.filter((attempt) =>
          attempt.status !== "failed" || (attemptId && attempt.id !== attemptId),
        );
        return new Response(null, { status: 204 });
      }
      if (url.includes("/render-attempts")) return json({ items: history, total: history.length });
      return json({ items: [], total: 0 });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const buttons = await screen.findAllByRole("button", { name: "Delete failed render" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Delete failed render" })).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Delete all failed renders" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Delete all failed renders" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Delete completed.mp4" })).toBeInTheDocument();
    expect(requests[0]).toMatch(/failed-render-attempts\?attempt_id=failed-1$/);
    expect(requests[1]).toMatch(/failed-render-attempts$/);
    confirm.mockRestore();
  });

  it("requires source image and audio before generating video", async () => {
    const requests: Array<{ url: string; method?: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, method: init?.method });
      if (url.includes("/topics/topic-1")) return json(topic({ video_prompt: "Saved prompt" }));
      if (url.includes("/on-demand-videos/topic-1")) return json(topic({ video_prompt: "Saved prompt" }));
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [{ id: "node-1", name: "ComfyUI", base_url: "http://comfy", is_active: true, health_status: "healthy", last_checked_at: null, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T00:00:00Z" }], total: 1 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const generateVideoButton = await screen.findByRole("button", { name: "Generate Video" });
    await waitFor(() => expect(generateVideoButton).toBeEnabled());
    fireEvent.click(generateVideoButton);

    const alerts = await screen.findAllByRole("alert");
    expect(alerts.map((alert) => alert.textContent)).toContain("Pick source image and audio file before generating video.");
    expect(requests.some((request) => request.url.includes("/render") && request.method === "POST")).toBe(false);
  });

  it("adds uploaded audio to Audio source and selects it", async () => {
    const uploadedAudio = { ...mediaAsset("audio-uploaded", "audio", "created-video_content1_0001-audio.mp3"), generation_metadata: { source: "upload", duration_seconds: 12.2 } };
    const oldSpeech = { ...mediaAsset("old-speech", "audio", "old-speech.mp3"), generation_metadata: { source: "tts", duration_seconds: 4 } };
    const archivedSpeech = { ...oldSpeech, kind: "audio_archive" };
    const requests: Array<{ url: string; method?: string; body?: string }> = [];
    let uploaded = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, method: init?.method, body: init?.body ? String(init.body) : undefined });
      if (url.includes("/topics/topic-1")) return json({ ...topic({ video_prompt: "Saved prompt" }), contents: [{ ...job({ video_prompt: "Saved prompt" }), audio_asset: uploaded ? uploadedAudio : oldSpeech, audio_assets: uploaded ? [archivedSpeech, uploadedAudio] : [oldSpeech] }] });
      if (url.includes("/on-demand-videos/topic-1")) return json({ ...topic({ video_prompt: "Saved prompt" }), contents: [{ ...job({ video_prompt: "Saved prompt" }), audio_asset: uploaded ? uploadedAudio : oldSpeech, audio_assets: uploaded ? [archivedSpeech, uploadedAudio] : [oldSpeech] }] });
      if (url.includes("/jobs/job-1/audio") && init?.method === "POST") {
        uploaded = true;
        return json({ ...job(), audio_asset: uploadedAudio, audio_assets: [archivedSpeech, uploadedAudio] });
      }
      if (url.includes("/jobs/job-1/render-overrides") && init?.method === "PATCH") return json({ ...job({ duration: 14 }), audio_asset: uploadedAudio, audio_assets: [archivedSpeech, uploadedAudio] });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    await waitFor(() => expect(screen.getByLabelText("Audio source")).toHaveValue("old-speech"));
    const audioInput = await screen.findByLabelText("Audio file", { selector: "input" });
    fireEvent.change(audioInput, { target: { files: [new File(["audio"], "manual.mp3", { type: "audio/mpeg" })] } });

    await waitFor(() => expect(requests.some((request) => request.url === "/api/v1/jobs/job-1/audio" && request.method === "POST")).toBe(true));
    expect(await screen.findByLabelText("Audio source")).toHaveValue("audio-uploaded");
    await waitFor(() => expect(screen.getByLabelText("Duration")).toHaveValue("14"));
    await waitFor(() => expect(requests.some((request) => request.url.endsWith("/render-overrides") && request.body?.includes('"duration":14'))).toBe(true));
    expect(screen.getByText("created-video_content1_0001-audio.mp3 · active")).toBeInTheDocument();
  });

  it("shows uploaded source image and audio in current Rendered LTX params", async () => {
    const originalImage = mediaAsset("image-old", "source_image", "old-source.png");
    const uploadedImage = { ...mediaAsset("image-new", "source_image", "created-video_0001.png"), generation_metadata: { source: "upload", original_filename: "new-source.png" } };
    const originalAudio = { ...mediaAsset("audio-old", "audio", "old-audio.mp3"), generation_metadata: { source: "upload", duration_seconds: 8 } };
    const uploadedAudio = { ...mediaAsset("audio-new", "audio", "created-video_0001.mp3"), generation_metadata: { source: "upload", duration_seconds: 11, original_filename: "new-audio.mp3" } };
    const workflow = workflowTemplate();
    const sizedWorkflow = { ...workflow, workflow_json: {
      ...workflow.workflow_json,
      imageResize: { class_type: "ImageScale", inputs: { width: 640, height: 480 } },
      video: { class_type: "EmptyLTXVLatentVideo", inputs: { width: ["width", 0], height: ["height", 0] } },
      width: { class_type: "PrimitiveInt", _meta: { title: "Width" }, inputs: { value: 768 } },
      height: { class_type: "PrimitiveInt", _meta: { title: "Height" }, inputs: { value: 512 } },
    } };
    const savedOverrides: Record<string, unknown>[] = [];
    let imageUploaded = false;
    let audioUploaded = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const currentImage = imageUploaded ? uploadedImage : originalImage;
      const currentAudio = audioUploaded ? uploadedAudio : originalAudio;
      const currentJob = { ...job({ video_prompt: "Elena says {{SCRIPT}}", duration: audioUploaded ? 12 : 9 }), source_image_asset: currentImage, audio_asset: currentAudio, audio_assets: [currentAudio] };
      if (url.includes("/topics/topic-1")) return json({ ...topic({ video_prompt: "Elena says {{SCRIPT}}", duration: audioUploaded ? 12 : 9 }), contents: [currentJob] });
      if (url.includes("/on-demand-videos/topic-1")) return json({ ...topic({ video_prompt: "Elena says {{SCRIPT}}", duration: audioUploaded ? 12 : 9 }), contents: [currentJob] });
      if (url.includes("/jobs/job-1/source-image") && init?.method === "POST") {
        imageUploaded = true;
        return json({ ...currentJob, source_image_asset: uploadedImage });
      }
      if (url.includes("/jobs/job-1/audio") && init?.method === "POST") {
        audioUploaded = true;
        return json({ ...currentJob, audio_asset: uploadedAudio, audio_assets: [uploadedAudio] });
      }
      if (url.includes("/jobs/job-1/render-overrides") && init?.method === "PATCH") {
        const overrides = JSON.parse(String(init.body));
        savedOverrides.push(overrides);
        return json({ ...currentJob, render_overrides: overrides, audio_asset: uploadedAudio, audio_assets: [uploadedAudio] });
      }
      if (url.includes("/workflow-templates")) return json({ items: [sizedWorkflow], total: 1 });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const imageInput = await screen.findByLabelText("Source image", { selector: "input" });
    fireEvent.change(imageInput, { target: { files: [new File(["image"], "new-source.png", { type: "image/png" })] } });
    await waitFor(() => expect(screen.getByText("Override image: new-source.png")).toBeInTheDocument());
    const audioInput = await screen.findByLabelText("Audio file", { selector: "input" });
    fireEvent.change(audioInput, { target: { files: [new File(["audio"], "new-audio.mp3", { type: "audio/mpeg" })] } });

    await waitFor(() => expect(screen.getByText("Override audio: new-audio.mp3")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByLabelText("Audio source")).toHaveValue("audio-new"));
    await waitFor(() => expect(savedOverrides).toContainEqual(expect.objectContaining({ duration: 12 })));
    const resolution = await screen.findByLabelText("Resolution preset");
    expect(within(resolution).getByRole("option", { name: "Workflow default (768 × 512)" })).toBeInTheDocument();
    fireEvent.change(resolution, { target: { value: "512x288" } });
    fireEvent.change(screen.getByLabelText("Aspect ratio"), { target: { value: "9:16" } });
    expect(resolution).toHaveValue("288x512");
    expect(within(resolution).getByRole("option", { name: "576 × 1024" })).toBeInTheDocument();
    expect(within(resolution).queryByRole("option", { name: "1024 × 576" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Rendered LTX params" }));

    const paramsDialog = screen.getByRole("dialog", { name: "Rendered LTX 2.3 params" });
    expect(within(paramsDialog).getByText("new-source.png")).toBeVisible();
    expect(within(paramsDialog).getByText("new-audio.mp3")).toBeVisible();
    expect(within(paramsDialog).getByText("Elena says Saved script")).toBeVisible();
    expect(within(paramsDialog).getByText("12")).toBeVisible();
    expect(within(paramsDialog).getByText("Width").closest("article")).toHaveTextContent("288");
    expect(within(paramsDialog).getByText("Height").closest("article")).toHaveTextContent("512");
    expect(within(paramsDialog).getByText("width.value")).toBeVisible();
    expect(within(paramsDialog).getByText("height.value")).toBeVisible();
    fireEvent.click(within(paramsDialog).getByRole("button", { name: "Close rendered LTX params" }));
    fireEvent.click(screen.getByRole("button", { name: "Save LTX controls" }));
    await waitFor(() => expect(savedOverrides).toContainEqual(expect.objectContaining({ width: 288, height: 512 })));
  });

  it("updates LTX duration to selected audio duration plus one second", async () => {
    const activeAudio = { ...mediaAsset("audio-1", "audio", "active.mp3"), generation_metadata: { source: "tts", duration_seconds: 8.1 } };
    const archivedAudio = { ...mediaAsset("audio-2", "audio_archive", "alternate.mp3"), generation_metadata: { source: "tts", duration_seconds: 17.01 } };
    const requests: Array<{ url: string; method?: string; body?: string }> = [];
    let confirmAudioSelection = () => {};
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, method: init?.method, body: init?.body ? String(init.body) : undefined });
      if (url.includes("/topics/topic-1")) return json({ ...topic({ video_prompt: "Saved prompt", duration: 9 }), contents: [{ ...job({ video_prompt: "Saved prompt", duration: 9 }), audio_asset: activeAudio, audio_assets: [activeAudio, archivedAudio] }] });
      if (url.includes("/on-demand-videos/topic-1")) return json({ ...topic({ video_prompt: "Saved prompt", duration: 9 }), contents: [{ ...job({ video_prompt: "Saved prompt", duration: 9 }), audio_asset: activeAudio, audio_assets: [activeAudio, archivedAudio] }] });
      if (url.includes("/jobs/job-1/audio/audio-2/active") && init?.method === "PATCH") {
        return new Promise<Response>((resolve) => {
          confirmAudioSelection = () => resolve(json({ ...job({ video_prompt: "Saved prompt", duration: 9 }), audio_asset: { ...archivedAudio, kind: "audio" }, audio_assets: [{ ...activeAudio, kind: "audio_archive" }, { ...archivedAudio, kind: "audio" }] }));
        });
      }
      if (url.includes("/jobs/job-1/render-overrides") && init?.method === "PATCH") {
        return json({ ...job({ video_prompt: "Saved prompt", duration: 19 }), audio_asset: { ...archivedAudio, kind: "audio" }, audio_assets: [{ ...activeAudio, kind: "audio_archive" }, { ...archivedAudio, kind: "audio" }] });
      }
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const durationInput = await screen.findByLabelText("Duration");
    await waitFor(() => expect(durationInput).toHaveValue("9"));
    fireEvent.change(screen.getByLabelText("Audio source"), { target: { value: "audio-2" } });

    await waitFor(() => expect(durationInput).toHaveValue("19"));
    expect(requests.some((request) => request.url.endsWith("/render-overrides"))).toBe(false);
    confirmAudioSelection();
    expect(requests.some((request) => request.url.endsWith("/audio/audio-2/active") && request.method === "PATCH")).toBe(true);
    await waitFor(() => expect(requests.some((request) => request.url.endsWith("/render-overrides") && request.body?.includes('"duration":19'))).toBe(true));
  });

  it("activates the selected Audio source before queuing video render", async () => {
    const activeAudio = { ...mediaAsset("audio-old", "audio", "old-active.mp3"), generation_metadata: { source: "upload", duration_seconds: 10 } };
    const generatedAudio = { ...mediaAsset("audio-generated", "audio_archive", "generated-speech.mp3"), generation_metadata: { source: "tts", duration_seconds: 21.2 } };
    const sourceImage = mediaAsset("image-1", "source_image", "source.png");
    const staleJob = { ...job({ video_prompt: "Saved prompt", duration: 30 }), source_image_asset: sourceImage, audio_asset: activeAudio, audio_assets: [activeAudio, generatedAudio] };
    const selectedJob = { ...job({ video_prompt: "Saved prompt", duration: 23 }), source_image_asset: sourceImage, audio_asset: { ...generatedAudio, kind: "audio" }, audio_assets: [{ ...activeAudio, kind: "audio_archive" }, { ...generatedAudio, kind: "audio" }] };
    const requests: Array<{ url: string; method?: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, method: init?.method });
      if (url.includes("/topics/topic-1")) return json({ ...topic({ video_prompt: "Saved prompt" }), contents: [staleJob] });
      if (url.endsWith("/api/v1/on-demand-videos/topic-1") && init?.method === "PUT") return json({ ...topic({ video_prompt: "Saved prompt" }), contents: [staleJob] });
      if (url.includes("/on-demand-videos/topic-1")) return json({ ...topic({ video_prompt: "Saved prompt" }), contents: [staleJob] });
      if (url.includes("/jobs/job-1/audio/audio-generated/active") && init?.method === "PATCH") return json(selectedJob);
      if (url.includes("/jobs/job-1/render-overrides") && init?.method === "PATCH") return json(selectedJob);
      if (url.includes("/jobs/job-1/render") && init?.method === "POST") return json({ id: "attempt-1", job_id: "job-1", render_profile_id: "profile-1", render_node_id: "node-1", workflow_template_id: "workflow-1", provider: "comfyui", status: "queued", progress: 0, external_job_id: null, output_filename: null, output_deleted_at: null, effective_values: {}, rendered_controls: [], assets: [], error_message: null, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T00:00:00Z" });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [{ id: "node-1", name: "ComfyUI", base_url: "http://comfy", is_active: true, health_status: "healthy", last_checked_at: null, created_at: "2026-08-10T00:00:00Z", updated_at: "2026-08-10T00:00:00Z" }], total: 1 });
      if (url.includes("/workflow-templates")) return json({ items: [], total: 0 });
      if (url.includes("/render-attempts")) return json({ items: [], total: 0 });
      return json({});
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const audioSource = await screen.findByLabelText("Audio source");
    await waitFor(() => expect(audioSource).toBeEnabled());
    fireEvent.change(audioSource, { target: { value: "audio-generated" } });
    await waitFor(() => expect(audioSource).toHaveValue("audio-generated"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate Video" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Generate Video" }));

    await waitFor(() => expect(requests.some((request) => request.url.includes("/jobs/job-1/render") && request.method === "POST")).toBe(true));
    const lastActivateIndex = requests.map((request) => request.url).lastIndexOf("/api/v1/jobs/job-1/audio/audio-generated/active");
    const renderIndex = requests.findIndex((request) => request.url.includes("/jobs/job-1/render") && request.method === "POST");
    expect(lastActivateIndex).toBeGreaterThanOrEqual(0);
    expect(renderIndex).toBeGreaterThan(lastActivateIndex);
  });

  it("queues each click with its own inputs and shows saved history metadata", async () => {
    const audio = { ...mediaAsset("audio-1", "audio", "recording.mp3"), generation_metadata: { voice_name: "Captured voice", duration_seconds: 12.24 } };
    const image = mediaAsset("image-1", "source_image", "source.png");
    const video = mediaAsset("video-1", "video", "done.mp4");
    const completed = renderAttempt(video, { effective_values: { seed: 42 } });
    const running = renderAttempt(video, {
      id: "running",
      status: "rendering",
      progress: 28,
      output_filename: null,
      completed_at: null,
      assets: [],
      effective_values: { requested_inputs: { values: { topic: "Elena’s original title" } } },
    });
    const waiting = renderAttempt(video, { id: "waiting", status: "queued", assets: [], output_filename: null });
    const submissions: unknown[] = [];
    let removed = false;
    document.title = "UGC Creator";
    let acceptFirst = () => {};
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/topics/topic-1")) return json({ ...topic(), contents: [{
        ...job(), source_image_asset: image, audio_asset: audio, audio_assets: [audio], status: "rendering",
      }] });
      if (url.includes("/jobs/job-1/render/queued") && init?.method === "POST") {
        submissions.push(JSON.parse(String(init.body)));
        if (submissions.length === 1) {
          return new Promise<Response>((resolve) => { acceptFirst = () => resolve(json(waiting)); });
        }
        return json(waiting);
      }
      if (url.includes("/render-attempts/waiting/cancel?queued_only=true") && init?.method === "POST") {
        removed = true;
        return json({ ...waiting, status: "cancelled" });
      }
      if (url.includes("/render-attempts")) return json({ items: removed ? [completed] : [waiting, { ...running, progress: submissions.length === 2 ? 64 : 28 }, completed] });
      if (url.includes("/render-nodes")) return json({ items: [{ id: "node-1", is_active: true, health_status: "healthy" }] });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile] });
      return json({ items: [] });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);
    const audioMetadata = await screen.findByRole("button", { name: "Show metadata for recording.mp3" });
    expect(screen.getByLabelText("Audio length 12.2 s")).toBeVisible();
    expect(audioMetadata).toHaveAttribute("aria-haspopup", "dialog");
    expect(audioMetadata.querySelector("svg")).toBeInTheDocument();
    expect(audioMetadata.textContent).toBe("");
    fireEvent.click(audioMetadata);
    const audioDialog = screen.getByRole("dialog", { name: "Audio metadata" });
    expect(within(audioDialog).getByLabelText("Metadata JSON")).toHaveTextContent("Captured voice");
    fireEvent.keyDown(screen.getByRole("button", { name: "Close metadata" }), { key: "Escape" });
    expect(audioDialog).not.toBeInTheDocument();
    expect(audioMetadata).toHaveFocus();

    const videoMetadata = screen.getByRole("button", { name: "Show metadata for done.mp4" });
    expect(videoMetadata.querySelector("svg")).toBeInTheDocument();
    fireEvent.click(videoMetadata);
    expect(screen.getByRole("dialog", { name: "Video metadata" })).toHaveTextContent('"seed": 42');
    fireEvent.click(screen.getByRole("button", { name: "Close metadata" }));

    expect(screen.getByText("rendering · 28%").closest(".create-video-progress")).toHaveTextContent("Elena’s original title");
    expect(document.title).toBe("28% | UGC Creator");
    const generate = screen.getByRole("button", { name: "Generate Video" });
    const prompt = screen.getByLabelText("Video prompt");
    fireEvent.change(prompt, { target: { value: "First prompt" } });
    fireEvent.click(generate);
    await waitFor(() => expect(submissions).toHaveLength(1));
    expect(generate).toBeEnabled();
    fireEvent.change(prompt, { target: { value: "Second prompt" } });
    fireEvent.click(generate);
    acceptFirst();
    await waitFor(() => expect(submissions).toHaveLength(2));
    expect(submissions[0]).toMatchObject({
      source_image_asset_id: "image-1", audio_asset_id: "audio-1",
      render_overrides: { video_prompt: "First prompt" },
    });
    expect(submissions[1]).toMatchObject({ render_overrides: { video_prompt: "Second prompt" } });

    await waitFor(() => expect(document.title).toBe("64% | UGC Creator"));
    fireEvent.click(screen.getByRole("button", { name: "Remove from queue" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove from queue" })).not.toBeInTheDocument());
    expect(document.title).toBe("UGC Creator");
  });

  it("shows a cancel icon beside active render progress", async () => {
    const audioAsset = mediaAsset("audio-1", "audio", "active-audio.mp3");
    const sourceImage = mediaAsset("image-1", "source_image", "source.png");
    const activeAttempt = renderAttempt(mediaAsset("video-1", "video", "pending.mp4"), {
      status: "rendering",
      progress: 47,
      assets: [],
      output_filename: null,
      completed_at: null,
    });
    const requests: Array<{ url: string; method?: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, method: init?.method });
      if (url.includes("/topics/topic-1")) {
        return json({ ...topic(), contents: [{ ...job(), source_image_asset: sourceImage, audio_asset: audioAsset, audio_assets: [audioAsset], status: "rendering" }] });
      }
      if (url.includes("/render-attempts/attempt-1/cancel") && init?.method === "POST") {
        return json({ ...activeAttempt, status: "cancelled", progress: 47, error_message: "Render cancelled." });
      }
      if (url.includes("/render-attempts")) return json({ items: [activeAttempt], total: 1 });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/workflow-templates")) return json({ items: [], total: 0 });
      return json({ items: [], total: 0, limit: 50, offset: 0 });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const cancelButton = await screen.findByRole("button", { name: "Cancel rendering" });
    fireEvent.click(cancelButton);

    await waitFor(() => expect(requests).toContainEqual({ url: "/api/v1/render-attempts/attempt-1/cancel", method: "POST" }));
  });

  it("allows deleting a completed video while a new render is active", async () => {
    const audioAsset = mediaAsset("audio-1", "audio", "active-audio.mp3");
    const sourceImage = mediaAsset("image-1", "source_image", "source.png");
    const completedVideo = mediaAsset("video-completed", "video", "completed.mp4");
    const completedAttempt = renderAttempt(completedVideo, { id: "attempt-completed" });
    const activeAttempt = renderAttempt(mediaAsset("video-active", "video", "pending.mp4"), {
      id: "attempt-active",
      status: "rendering",
      progress: 47,
      assets: [],
      output_filename: null,
      completed_at: null,
    });
    const requests: Array<{ url: string; method?: string }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, method: init?.method });
      if (url.includes("/topics/topic-1")) {
        return json({ ...topic(), contents: [{ ...job(), source_image_asset: sourceImage, audio_asset: audioAsset, audio_assets: [audioAsset], status: "rendering" }] });
      }
      if (url.includes("/render-attempts")) return json({ items: [activeAttempt, completedAttempt], total: 2 });
      if (url.includes("/render-profiles")) return json({ items: [renderProfile], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/voices")) return json({ items: [{ voice_id: "voice-hope", name: "Hope", category: "saved", description: null, preview_url: null }], total: 1 });
      if (url.includes("/tts-providers/elevenlabs/usage")) return json({ provider: "elevenlabs", configured: true, used_units: 10, limit_units: 100, remaining_units: 90, resets_at_unix: null, unit: "characters" });
      if (url.includes("/render-nodes")) return json({ items: [], total: 0 });
      if (url.includes("/workflow-templates")) return json({ items: [], total: 0 });
      if (url.endsWith("/api/v1/assets/video-completed") && init?.method === "DELETE") return json({}, 204);
      return json({ items: [], total: 0, limit: 50, offset: 0 });
    });

    render(<Providers><CreateVideoPanel topicId="topic-1" /></Providers>);

    const deleteCompletedVideo = await screen.findByRole("button", { name: "Delete completed.mp4" });
    expect(deleteCompletedVideo).toBeEnabled();
    fireEvent.click(deleteCompletedVideo);

    await waitFor(() => expect(requests).toContainEqual({ url: "/api/v1/assets/video-completed", method: "DELETE" }));
  });
});

function mediaAsset(id: string, kind: string, filename: string) {
  return {
    id,
    job_id: "job-1",
    kind,
    filename,
    content_type: kind === "video" ? "video/mp4" : "audio/mpeg",
    size_bytes: 123,
    generation_metadata: null,
    download_url: `/api/v1/assets/${id}/download`,
    created_at: "2026-08-10T00:00:00Z",
  };
}

function renderAttempt(asset: ReturnType<typeof mediaAsset>, overrides: Record<string, unknown> = {}) {
  return {
    id: "attempt-1",
    job_id: "job-1",
    render_profile_id: "profile-1",
    render_node_id: "node-1",
    workflow_template_id: "workflow-1",
    provider: "comfyui",
    status: "completed",
    progress: 100,
    external_job_id: "prompt-1",
    error_message: null,
    output_filename: asset.filename,
    output_deleted_at: null,
    effective_values: {},
    rendered_controls: [
      { label: "Image source", node_id: "269", input_name: "image", value: "attempt-image.png" },
      { label: "Audio source", node_id: "276", input_name: "audio", value: "attempt-audio.mp3" },
      { label: "Prompt", node_id: "340:319", input_name: "value", value: "Elena says: Saved script" },
      { label: "Seed", node_id: "340:286", input_name: "noise_seed", value: 987654 },
    ],
    submitted_at: "2026-08-10T00:00:05Z",
    completed_at: "2026-08-10T00:01:35Z",
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
    assets: [asset],
    ...overrides,
  };
}

function workflowTemplate() {
  return {
    id: "workflow-1",
    name: "LTX remembered workflow",
    description: null,
    workflow_json: {
      image: { class_type: "LoadImage", inputs: { image: "workflow-source.png" } },
      audio: { class_type: "LoadAudio", inputs: { audio: "workflow-audio.mp3" } },
      prompt: { _meta: { title: "Prompt" }, class_type: "PrimitiveStringMultiline", inputs: { value: "Remembered LTX prompt" } },
      duration: { _meta: { title: "Duration" }, class_type: "PrimitiveInt", inputs: { value: 30 } },
    },
    metadata_json: {},
    version: 1,
    checksum: "abc",
    bindings: [],
    created_at: "2026-08-10T00:00:00Z",
    updated_at: "2026-08-10T00:00:00Z",
  };
}

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}
