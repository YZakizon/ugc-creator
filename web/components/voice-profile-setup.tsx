"use client";

import React, { FormEvent, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { HumanDate } from "@/components/date-display";
import { ConfirmDialog, Toast } from "@/components/feedback";
import { ApiRequestError, createVoicePreview, createVoiceProfile, deleteVoiceProfile, getVoicePreview, getVoiceProfiles, updateVoiceProfile } from "@/lib/api";
import type { ResourceReference, VoiceProfile, VoiceProfileInUseDetail } from "@/lib/api";

type VoiceForm = {
  profileName: string;
  voiceName: string;
  voiceId: string;
  model: string;
  speed: string;
  stability: string;
  similarity: string;
  exaggeration: string;
  languageOverride: boolean;
  languageCode: string;
  outputFormat: string;
  speakerBoost: boolean;
};

const emptyVoiceForm: VoiceForm = {
  profileName: "",
  voiceName: "",
  voiceId: "",
  model: "eleven_multilingual_v2",
  speed: "1",
  stability: "50",
  similarity: "75",
  exaggeration: "50",
  languageOverride: false,
  languageCode: "en",
  outputFormat: "mp3_44100_128",
  speakerBoost: true,
};

function toForm(profile: VoiceProfile): VoiceForm {
  return {
    profileName: profile.name,
    voiceName: String(profile.extra_settings.voice_name ?? ""),
    voiceId: profile.provider_voice_id,
    model: profile.provider_model ?? "",
    speed: String(profile.speed),
    stability: profile.stability === null ? "50" : String(Math.round(profile.stability * 100)),
    similarity: profile.similarity === null ? "75" : String(Math.round(profile.similarity * 100)),
    exaggeration: profile.style_exaggeration === null ? "50" : String(Math.round(profile.style_exaggeration * 100)),
    languageOverride: profile.extra_settings.language_override_enabled === true,
    languageCode: String(profile.extra_settings.language_code ?? "en"),
    outputFormat: String(profile.extra_settings.output_format ?? "mp3_44100_128"),
    speakerBoost: profile.extra_settings.use_speaker_boost !== false,
  };
}

function optionalNumber(value: string): number | undefined {
  return value === "" ? undefined : Number(value) / 100;
}

function voicePayload(form: VoiceForm) {
  return {
    name: form.profileName.trim(),
    provider: "elevenlabs",
    provider_voice_id: form.voiceId.trim(),
    provider_model: form.model.trim() || undefined,
    speed: Number(form.speed),
    stability: optionalNumber(form.stability),
    similarity: optionalNumber(form.similarity),
    style_exaggeration: optionalNumber(form.exaggeration),
    extra_settings: {
      voice_name: form.voiceName.trim(),
      language_override_enabled: form.languageOverride,
      language_code: form.languageOverride ? form.languageCode : null,
      output_format: form.outputFormat,
      use_speaker_boost: form.speakerBoost,
    },
  };
}

export function VoiceProfileSetup() {
  const queryClient = useQueryClient();
  const voicesQuery = useQuery({ queryKey: ["voice-profiles"], queryFn: getVoiceProfiles });
  const [activeTab, setActiveTab] = useState<"create" | "list">("list");
  const [form, setForm] = useState<VoiceForm>(emptyVoiceForm);
  const formRef = useRef<VoiceForm>(emptyVoiceForm);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<VoiceForm>(emptyVoiceForm);
  const editFormRef = useRef<VoiceForm>(emptyVoiceForm);
  const [pendingDelete, setPendingDelete] = useState<VoiceProfile | null>(null);
  const [previewText, setPreviewText] = useState("Hello! This is a preview of the selected voice profile.");
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; variant: "success" | "danger"; profileLinks?: ResourceReference[] } | null>(null);

  const createMutation = useMutation({
    mutationFn: createVoiceProfile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["voice-profiles"] });
      setForm(emptyVoiceForm);
      formRef.current = emptyVoiceForm;
      setActiveTab("list");
      setToast({ message: "Voice profile created.", variant: "success" });
    },
    onError: (error) => setToast({ message: error.message, variant: "danger" }),
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, values }: { id: string; values: VoiceForm }) => updateVoiceProfile({ id, ...voicePayload(values) }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["voice-profiles"] });
      setToast({ message: "Voice profile updated.", variant: "success" });
    },
    onError: (error) => setToast({ message: error.message, variant: "danger" }),
  });
  const deleteMutation = useMutation({
    mutationFn: deleteVoiceProfile,
    onSuccess: (_, profileId) => {
      void queryClient.invalidateQueries({ queryKey: ["voice-profiles"] });
      if (expandedId === profileId) setExpandedId(null);
      setToast({ message: "Voice profile deleted.", variant: "success" });
    },
    onError: (error) => {
      const detail = voiceProfileConflictDetail(error);
      setToast({ message: error.message, variant: "danger", profileLinks: detail?.render_profiles });
    },
  });
  const previewMutation = useMutation({
    mutationFn: createVoicePreview,
    onSuccess: (preview) => setPreviewId(preview.id),
    onError: (error) => setToast({ message: error.message, variant: "danger" }),
  });
  const previewQuery = useQuery({
    queryKey: ["voice-preview", previewId],
    queryFn: () => getVoicePreview(previewId as string),
    enabled: previewId !== null,
    refetchInterval: (query) => ["queued", "generating"].includes(query.state.data?.status ?? "") ? 1500 : false,
  });

  function updateForm(field: keyof VoiceForm, value: string | boolean) {
    const next = { ...formRef.current, [field]: value } as VoiceForm;
    formRef.current = next;
    setForm(next);
  }

  function updateEditForm(field: keyof VoiceForm, value: string | boolean) {
    const next = { ...editFormRef.current, [field]: value } as VoiceForm;
    editFormRef.current = next;
    setEditForm(next);
  }

  function toggle(profile: VoiceProfile) {
    if (expandedId === profile.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(profile.id);
    setPreviewId(null);
    const values = toForm(profile);
    editFormRef.current = values;
    setEditForm(values);
  }

  return <div className="voice-profile-setup">
    <div className="profile-tabs" role="tablist" aria-label="Voice profile sections">
      <button className={`profile-tab${activeTab === "create" ? " active" : ""}`} type="button" role="tab" aria-selected={activeTab === "create"} onClick={() => setActiveTab("create")}>Create voice profile</button>
      <button className={`profile-tab${activeTab === "list" ? " active" : ""}`} type="button" role="tab" aria-selected={activeTab === "list"} onClick={() => setActiveTab("list")}>Voice profiles</button>
    </div>

    <div className="profile-tab-panel" role="tabpanel" hidden={activeTab !== "create"}>
      <form className="profile-form voice-config-form" onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); createMutation.mutate(voicePayload(formRef.current)); }}>
        <VoiceFields values={form} onChange={updateForm} />
        <div className="profile-create-actions"><button className="button button-primary" type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? "Creating…" : "Create voice profile"}</button></div>
      </form>
    </div>

    <div className="profile-tab-panel" role="tabpanel" hidden={activeTab !== "list"}>
      {voicesQuery.isLoading ? <div className="profile-empty compact-profile-empty"><p>Loading voice profiles…</p></div> : voicesQuery.isError ? <div className="profile-empty compact-profile-empty"><p className="form-error">Voice profiles are unavailable: {voicesQuery.error.message}</p></div> : voicesQuery.data?.items.length ? <div className="profile-list">
        {voicesQuery.data.items.map((profile) => <article className={`saved-profile${expandedId === profile.id ? " expanded" : ""}`} key={profile.id}>
          <div className="saved-profile-header"><button className="saved-profile-toggle" type="button" aria-label={`${expandedId === profile.id ? "Hide" : "Show"} ${profile.name} details`} aria-expanded={expandedId === profile.id} onClick={() => toggle(profile)}>
              <span className="profile-list-icon">◒</span>
              <span className="saved-profile-summary"><strong>{profile.name}</strong><small>Created <HumanDate value={profile.created_at} /> · Updated <HumanDate value={profile.updated_at} /></small></span>
              <svg className="profile-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5" /></svg>
            </button><button className="icon-button profile-icon-button danger" type="button" aria-label={`Delete ${profile.name}`} title="Delete voice profile" disabled={deleteMutation.isPending} onClick={() => setPendingDelete(profile)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg></button></div>
          {expandedId === profile.id && <form className="profile-form voice-config-form voice-config-edit" onSubmit={(event) => { event.preventDefault(); updateMutation.mutate({ id: profile.id, values: editFormRef.current }); }}>
            <VoiceFields values={editForm} onChange={updateEditForm} />
            <section className="profile-form-section voice-preview-section">
              <div className="profile-form-section-heading"><h3>Generate speech preview</h3><p>Test this saved ElevenLabs voice and download the generated audio.</p></div>
              <div className="voice-preview-controls">
                <label className="voice-preview-text">Text<textarea rows={5} maxLength={5000} value={previewText} onChange={(event) => setPreviewText(event.target.value)} placeholder="Enter text to generate speech…" /><small>{previewText.length} / 5000 characters</small></label>
                <div className="voice-preview-actions"><button className="button button-secondary" type="button" disabled={previewMutation.isPending || !previewText.trim()} onClick={() => previewMutation.mutate({ voiceProfileId: profile.id, text: previewText.trim() })}>{previewMutation.isPending ? "Queuing…" : "Generate speech"}</button>{previewQuery.data && <span className={`voice-preview-status ${previewQuery.data.status}`}>{previewQuery.data.status.replaceAll("_", " ")}</span>}</div>
                {previewQuery.data?.status === "completed" && previewQuery.data.download_url && <div className="voice-preview-result"><audio controls preload="metadata" src={previewQuery.data.download_url}>Your browser does not support audio playback.</audio><a className="button button-primary" href={previewQuery.data.download_url} download={previewQuery.data.filename ?? "voice-preview.mp3"}>Download audio</a></div>}
                {previewQuery.data?.status === "failed" && <p className="form-error" role="alert">{previewQuery.data.error_message ?? "Speech generation failed."}</p>}
              </div>
            </section>
            <div className="profile-create-actions"><button className="button button-primary" type="submit" disabled={updateMutation.isPending}>{updateMutation.isPending ? "Saving…" : "Save changes"}</button></div>
          </form>}
        </article>)}
      </div> : <div className="profile-empty compact-profile-empty"><div className="profile-list-icon">◒</div><div><h3>No voice profiles yet</h3><p>Create an ElevenLabs voice configuration, then attach it to a render profile.</p></div></div>}
    </div>
    <ConfirmDialog open={pendingDelete !== null} title="Delete voice profile?" message={pendingDelete ? `“${pendingDelete.name}” will be permanently removed. Deletion is blocked while it is attached to a render profile or character.` : ""} confirmLabel="Delete" onCancel={() => setPendingDelete(null)} onConfirm={() => { if (pendingDelete) deleteMutation.mutate(pendingDelete.id); setPendingDelete(null); }} />
    {toast && <Toast message={toast.message} variant={toast.variant} content={toast.profileLinks?.length ? <span className="voice-delete-conflict"><span>{toast.message}</span><span className="toast-profile-links">{toast.profileLinks.map((profile) => <Link key={profile.id} href={`/profiles#profile-${profile.id}`}>Open {profile.name} · {profile.id}</Link>)}</span></span> : undefined} onClose={() => setToast(null)} />}
  </div>;
}

function voiceProfileConflictDetail(error: Error): VoiceProfileInUseDetail | null {
  if (!(error instanceof ApiRequestError) || typeof error.detail !== "object" || error.detail === null) return null;
  const detail = error.detail as Partial<VoiceProfileInUseDetail>;
  return detail.code === "voice_profile_in_use" && Array.isArray(detail.render_profiles)
    ? detail as VoiceProfileInUseDetail
    : null;
}

function VoiceFields({ values, onChange }: { values: VoiceForm; onChange: (field: keyof VoiceForm, value: string | boolean) => void }) {
  return <>
    <section className="profile-form-section">
      <div className="profile-form-section-heading"><h3>Voice identity</h3><p>Name this reusable configuration and identify the ElevenLabs voice.</p></div>
      <div className="profile-form-fields">
        <label>Voice profile name<input required value={values.profileName} onChange={(event) => onChange("profileName", event.target.value)} placeholder="Elena — Hope" /></label>
        <label>Provider / renderer<div className="eleven-setting-select disabled"><span className="eleven-provider-mark">E</span><strong>ElevenLabs</strong></div></label>
        <label>Voice name<div className="eleven-setting-input"><span className="eleven-voice-orb" /><input required value={values.voiceName} onChange={(event) => onChange("voiceName", event.target.value)} placeholder="Hope — upbeat and clear" /></div></label>
        <label>Voice ID<input required value={values.voiceId} onChange={(event) => onChange("voiceId", event.target.value)} placeholder="ElevenLabs voice ID" /></label>
        <label className="profile-field-wide">Model<select value={values.model} onChange={(event) => onChange("model", event.target.value)}><option value="eleven_multilingual_v2">Eleven Multilingual v2</option><option value="eleven_turbo_v2_5">Eleven Turbo v2.5</option><option value="eleven_v3">Eleven v3</option></select></label>
      </div>
    </section>
    <section className="profile-form-section">
      <div className="profile-form-section-heading"><h3>ElevenLabs parameters</h3><p>Values are normalized and validated before synthesis.</p></div>
      <div className="eleven-settings-stack">
        <VoiceSlider label="Speed" low="Slower" high="Faster" min="0.7" max="1.2" step="0.01" value={values.speed} onChange={(value) => onChange("speed", value)} />
        <VoiceSlider label="Stability" low="More variable" high="More stable" min="0" max="100" step="1" value={values.stability} suffix="%" onChange={(value) => onChange("stability", value)} />
        <VoiceSlider label="Similarity" low="Low" high="High" min="0" max="100" step="1" value={values.similarity} suffix="%" onChange={(value) => onChange("similarity", value)} />
        <VoiceSlider label="Style Exaggeration" low="None" high="Exaggerated" min="0" max="100" step="1" value={values.exaggeration} suffix="%" onChange={(value) => onChange("exaggeration", value)} />
        <div className="eleven-toggle-row"><span><strong>Language Override</strong><small>Force a specific language for this voice.</small></span><button className={`switch-control${values.languageOverride ? " active" : ""}`} type="button" role="switch" aria-checked={values.languageOverride} aria-label="Language Override" onClick={() => onChange("languageOverride", !values.languageOverride)}><span /></button></div>
        {values.languageOverride && <label className="eleven-select-field">Language<select value={values.languageCode} onChange={(event) => onChange("languageCode", event.target.value)}><option value="en">English</option><option value="es">Spanish</option><option value="fr">French</option><option value="de">German</option><option value="it">Italian</option><option value="pt">Portuguese</option></select></label>}
        <label className="eleven-select-field">Output Format<select value={values.outputFormat} onChange={(event) => onChange("outputFormat", event.target.value)}><option value="mp3_44100_128">MP3 44.1 kHz (128kbps)</option><option value="mp3_44100_192">MP3 44.1 kHz (192kbps)</option><option value="pcm_44100">PCM 44.1 kHz</option><option value="wav_44100">WAV 44.1 kHz</option></select></label>
        <div className="eleven-toggle-row speaker-boost-row"><span><strong>Speaker boost</strong><small>Increase similarity to the original speaker.</small></span><button className={`switch-control${values.speakerBoost ? " active" : ""}`} type="button" role="switch" aria-checked={values.speakerBoost} aria-label="Speaker boost" onClick={() => onChange("speakerBoost", !values.speakerBoost)}><span /></button></div>
        <button className="eleven-reset" type="button" onClick={() => { onChange("speed", "1"); onChange("stability", "50"); onChange("similarity", "75"); onChange("exaggeration", "50"); onChange("languageOverride", false); onChange("outputFormat", "mp3_44100_128"); onChange("speakerBoost", true); }}>↶ Reset values</button>
      </div>
    </section>
  </>;
}

function VoiceSlider({ label, low, high, min, max, step, value, suffix = "", onChange }: { label: string; low: string; high: string; min: string; max: string; step: string; value: string; suffix?: string; onChange: (value: string) => void }) {
  return <label className="eleven-slider"><span className="eleven-slider-title"><strong>{label}</strong><output aria-hidden="true">{value}{suffix}</output></span><span className="eleven-slider-hints"><small>{low}</small><small>{high}</small></span><input aria-label={label} type="range" min={min} max={max} step={step} value={value || min} onInput={(event) => onChange(event.currentTarget.value)} /></label>;
}
