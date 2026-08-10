"use client";

import React, { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { HumanDate } from "@/components/date-display";
import { generateJobContent, generateJobSpeech, getBatches, getDashboardSummary, getRenderAttempts, getRenderNodes, getRenderProfiles, queueJobRender, updateJobRenderProfile } from "@/lib/api";
import type { Job, RenderAttempt } from "@/lib/api";

export function failedJobRetryKind(
  job: Pick<Job, "status" | "speech_script">,
  attempt?: Pick<RenderAttempt, "status">,
): "content" | "tts" | "render" | null {
  if (job.status !== "failed") return null;
  if (attempt?.status === "failed" && Boolean(job.speech_script)) return "render";
  return job.speech_script ? "tts" : "content";
}

export function jobFailureMessage(
  job: Pick<Job, "status" | "error_message">,
): string | null {
  if (job.status !== "failed") return null;
  return job.error_message?.trim() || "This job failed without a detailed error. Retry it or check the worker logs.";
}

export function renderProgressLabel(
  attempt: Pick<RenderAttempt, "status" | "progress">,
): string {
  if (attempt.status === "rendering" && attempt.progress <= 1) {
    return "Progress unavailable (polling)";
  }
  return `${attempt.progress}%`;
}

export function speechScriptLines(script: string): string[] {
  return script
    .replace(/\r\n?/g, "\n")
    .split(/\n+/)
    .flatMap((paragraph) => paragraph.match(/[^.!?]+(?:[.!?]+[”"']?|$)/g) ?? [])
    .map((line) => line.trim())
    .filter(Boolean);
}

function StatCard({ label, value, hint, icon, tone }: {
  label: string;
  value: number | string;
  hint: string;
  icon: string;
  tone: "blue" | "purple" | "green" | "orange";
}) {
  return (
    <article className="stat-card">
      <div className="stat-top"><span>{label}</span><span className={`stat-icon ${tone}`}>{icon}</span></div>
      <strong>{value}</strong><small>{hint}</small>
    </article>
  );
}

export function DashboardStats() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
    refetchInterval: 5000,
  });
  const value = (key: "in_progress" | "ready_to_render" | "completed_videos" | "render_profiles") => data?.[key] ?? "—";
  const hint = isError ? "API unavailable" : isLoading ? "Loading…" : undefined;

  return (
    <section className="stats-grid" aria-label="Workspace overview">
      <StatCard label="In progress" value={value("in_progress")} hint={hint ?? (data?.in_progress ? "Jobs are actively processing" : "No active jobs right now")} icon="◷" tone="blue" />
      <StatCard label="Ready to render" value={value("ready_to_render")} hint={hint ?? (data?.ready_to_render ? "Content is ready for rendering" : "No content waiting to render")} icon="✦" tone="purple" />
      <StatCard label="Completed videos" value={value("completed_videos")} hint={hint ?? (data?.completed_videos ? "Available in your library" : "No completed videos yet")} icon="✓" tone="green" />
      <StatCard label="Render profiles" value={value("render_profiles")} hint={hint ?? (data?.render_profiles ? "Reusable configurations available" : "Configure your first profile")} icon="⌘" tone="orange" />
    </section>
  );
}

export function CurrentDate() {
  const [date, setDate] = useState("");
  useEffect(() => {
    setDate(new Intl.DateTimeFormat(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    }).format(new Date()));
  }, []);
  return <p className="eyebrow">{date || "Today"}</p>;
}

function JobResult({ title, value }: { title: string; value: Record<string, unknown> | null }) {
  if (!value) return null;
  return <section className="job-result-block"><h4>{title}</h4><pre>{JSON.stringify(value, null, 2)}</pre></section>;
}

function InlineId({ label, value }: { label: string; value: string }) {
  const [visible, setVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const write = navigator.clipboard?.writeText(value);
    if (!write) return;
    void write.then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }).catch(() => undefined);
  };
  return <div className="job-inline-id"><button className="job-id-icon" type="button" aria-label={`${visible ? "Hide" : "Show"} ${label}`} title={`${visible ? "Hide" : "Show"} ${label}`} onClick={() => setVisible((current) => !current)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" /><circle cx="12" cy="12" r="2.5" /></svg></button>{visible && <><code>{value}</code><button className="job-id-icon" type="button" aria-label={`Copy ${label}`} title={`Copy ${label}`} onClick={copy}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg></button>{copied && <span role="status">Copied</span>}</>}
  </div>;
}

type ContentTab = "script" | "instagram" | "tiktok";
type GenerationTab = "speech" | "render";

export function RecentJobs({ contentGenerationReady, speechGenerationReady, detailed = false }: { contentGenerationReady: boolean; speechGenerationReady: boolean; detailed?: boolean }) {
  const queryClient = useQueryClient();
  const [contentTabs, setContentTabs] = useState<Record<string, ContentTab>>({});
  const [generationTabs, setGenerationTabs] = useState<Record<string, GenerationTab>>({});
  const [profileSelections, setProfileSelections] = useState<Record<string, string>>({});
  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
    refetchInterval: 5000,
  });
  const nodes = useQuery({ queryKey: ["render-nodes"], queryFn: getRenderNodes });
  const attempts = useQuery({ queryKey: ["render-attempts"], queryFn: getRenderAttempts, refetchInterval: 5000 });
  const batches = useQuery({ queryKey: ["batches"], queryFn: getBatches, enabled: detailed });
  const profiles = useQuery({ queryKey: ["render-profiles"], queryFn: getRenderProfiles, enabled: detailed });
  const contentMutation = useMutation({
    mutationFn: generateJobContent,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    },
  });
  const speechMutation = useMutation({
    mutationFn: generateJobSpeech,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    },
  });
  const renderMutation = useMutation({
    mutationFn: ({ jobId, nodeId }: { jobId: string; nodeId: string }) => queueJobRender(jobId, nodeId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["render-attempts"] });
    },
  });
  const profileMutation = useMutation({
    mutationFn: ({ jobId, profileId }: { jobId: string; profileId: string }) => updateJobRenderProfile(jobId, profileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
  });
  const jobs = data?.recent_jobs ?? [];

  if (isLoading) {
    return <div className="empty-state compact-empty"><p>Loading recent jobs…</p></div>;
  }
  if (isError) {
    return <div className="empty-state compact-empty"><p>Recent jobs are temporarily unavailable.</p></div>;
  }
  if (jobs.length === 0) {
    return (
      <div className="empty-state compact-empty">
        <div className="empty-icon">◷</div>
        <h3>No jobs yet</h3>
        <p>Your generated content and video jobs will show up here.</p>
        <a className="button button-secondary" href="#new-batch">Create your first batch</a>
      </div>
    );
  }

  return (
    <div className="jobs-list">
      {jobs.map((job) => {
        const attempt = attempts.data?.items.find((item) => item.job_id === job.id);
        const failedContent = failedJobRetryKind(job, attempt) === "content";
        const failedRender = failedJobRetryKind(job, attempt) === "render";
        const failedSpeech = failedJobRetryKind(job, attempt) === "tts";
        const failureMessage = jobFailureMessage(job);
        const canRender = job.status === "tts_ready" || job.status === "ready_to_render" || failedRender;
        const contentAction = <>
          {(job.status === "draft" || failedContent) && (
            <button
              className="job-action"
              type="button"
              disabled={contentMutation.isPending || !contentGenerationReady}
              title={contentGenerationReady ? undefined : "Set OPENAI_API_KEY in the root .env file and restart Docker"}
              onClick={() => contentMutation.mutate(job.id)}
            >
              {contentMutation.isPending && contentMutation.variables === job.id ? "Queuing…" : contentGenerationReady ? "Generate content" : "OpenAI setup required"}
            </button>
          )}
        </>;
        const speechAction = <>
          {(job.status === "content_ready" || failedSpeech) && (
            <button
              className="job-action"
              type="button"
              disabled={speechMutation.isPending || !speechGenerationReady}
              title={speechGenerationReady ? undefined : "Set ELEVENLABS_API_KEY in the root .env file and restart Docker"}
              onClick={() => speechMutation.mutate(job.id)}
            >
              {speechMutation.isPending && speechMutation.variables === job.id ? "Queuing…" : speechGenerationReady ? failedSpeech ? "Retry speech" : "Generate speech" : "ElevenLabs setup required"}
            </button>
          )}
        </>;
        const renderAction = <>
          {canRender && (
            <button className="job-action" type="button" disabled={renderMutation.isPending || !nodes.data?.items.some((node) => node.is_active)} onClick={() => { const node = nodes.data?.items.find((item) => item.health_status === "healthy") ?? nodes.data?.items.find((item) => item.is_active); if (node) renderMutation.mutate({ jobId: job.id, nodeId: node.id }); }}>{renderMutation.isPending && renderMutation.variables?.jobId === job.id ? "Queuing render…" : failedRender ? "Retry render" : "Render with ComfyUI"}</button>
          )}
        </>;
        const actions = <>{contentAction}{speechAction}{renderAction}</>;

        if (detailed) {
          const hasGeneratedContent = Boolean(job.speech_script || job.hook || job.instagram_metadata || job.tiktok_metadata);
          const contentTab = contentTabs[job.id] ?? "script";
          const generationTab = generationTabs[job.id] ?? "speech";
          const batchName = batches.data?.items?.find((batch) => batch.id === job.batch_id)?.name ?? (batches.isLoading ? "Loading batch…" : "Batch unavailable");
          const profile = profiles.data?.items?.find((item) => item.id === job.render_profile_id);
          const profileName = profile?.name ?? (profiles.isLoading ? "Loading profile…" : job.render_profile_id ? "Unavailable profile" : "Not assigned");
          const selectedProfileId = profileSelections[job.id] ?? job.render_profile_id ?? "";
          const profileChanged = selectedProfileId !== (job.render_profile_id ?? "");
          const profileLocked = ["queued", "submitting_render", "rendering", "downloading_output", "completed"].includes(job.status);
          return <details className="job-card" key={job.id}>
            <summary className="job-card-summary">
              <span className="job-status-dot" />
              <span className="job-card-title"><strong>{job.topic}</strong><small><span>Batch: {batchName}</span><span>Render: {profileName}</span><span>{job.status.replaceAll("_", " ")} · Updated <HumanDate value={job.updated_at} /></span></small></span>
              <b>{job.target_duration_seconds}s</b>
              {attempt && <small className="job-render-progress">{attempt.status.replaceAll("_", " ")} · {renderProgressLabel(attempt)}</small>}
              <span className="job-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div className="job-card-details">
              <div className="job-context"><div><span>Job</span><strong>{job.topic}</strong><InlineId label="Job ID" value={job.id} /></div><div><span>Batch</span><strong>{batchName}</strong><InlineId label="Batch ID" value={job.batch_id} /></div><div><span>Render profile</span><strong>{profileName}</strong>{job.render_profile_id && <InlineId label="Render profile ID" value={job.render_profile_id} />}</div><div><span>Content model</span><strong>{job.llm_provider && job.llm_model ? `${job.llm_provider} · ${job.llm_model}` : "Not generated"}</strong></div></div>
              {failureMessage && <p className="job-error" role="alert">{failureMessage}</p>}
              <section className="job-results job-content-section" aria-label={`Content results for ${job.topic}`}>
                <div className="job-tabs" role="tablist" aria-label="Generated content">
                  <button type="button" role="tab" aria-selected={contentTab === "script"} className={contentTab === "script" ? "active" : ""} onClick={() => setContentTabs((current) => ({ ...current, [job.id]: "script" }))}>Hook + Speech Script</button>
                  <button type="button" role="tab" aria-selected={contentTab === "instagram"} className={contentTab === "instagram" ? "active" : ""} onClick={() => setContentTabs((current) => ({ ...current, [job.id]: "instagram" }))}>Instagram</button>
                  <button type="button" role="tab" aria-selected={contentTab === "tiktok"} className={contentTab === "tiktok" ? "active" : ""} onClick={() => setContentTabs((current) => ({ ...current, [job.id]: "tiktok" }))}>TikTok</button>
                </div>
                {!hasGeneratedContent && <p className="field-hint">No generated content yet.</p>}
                <div role="tabpanel" hidden={contentTab !== "script"}>{job.hook && <div className="job-result-block"><h4>Hook</h4><p>{job.hook}</p></div>}{job.speech_script && <div className="job-result-block"><h4>Speech script</h4><div className="job-script">{speechScriptLines(job.speech_script).map((line, index) => <p key={`${index}-${line}`}>{line}</p>)}</div></div>}{contentAction}</div>
                <div role="tabpanel" hidden={contentTab !== "instagram"}><JobResult title="Instagram" value={job.instagram_metadata} />{!job.instagram_metadata && <p className="field-hint">Instagram content has not been generated.</p>}</div>
                <div role="tabpanel" hidden={contentTab !== "tiktok"}><JobResult title="TikTok" value={job.tiktok_metadata} />{!job.tiktok_metadata && <p className="field-hint">TikTok content has not been generated.</p>}</div>
              </section>
              <section className="job-results job-generation-section" aria-label={`Generation steps for ${job.topic}`}>
                <div className="job-tabs generation-tabs" role="tablist" aria-label="Generation steps"><button type="button" role="tab" aria-selected={generationTab === "speech"} className={generationTab === "speech" ? "active" : ""} onClick={() => setGenerationTabs((current) => ({ ...current, [job.id]: "speech" }))}>Generate speech</button><button type="button" role="tab" aria-selected={generationTab === "render"} className={generationTab === "render" ? "active" : ""} onClick={() => setGenerationTabs((current) => ({ ...current, [job.id]: "render" }))}>Render ComfyUI</button></div>
                <div className="job-generation-panel" role="tabpanel" hidden={generationTab !== "speech"}><p className="field-hint">Create ElevenLabs speech from the generated script.</p>{speechAction}{job.audio_asset && <div className="job-audio-result"><audio controls preload="none" src={job.audio_asset.download_url}>Your browser does not support audio playback.</audio><a className="voice-preview-download" href={job.audio_asset.download_url} download={job.audio_asset.filename} aria-label="Download generated speech" title="Download audio"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M5 21h14" /></svg></a></div>}</div>
                <div className="job-generation-panel" role="tabpanel" hidden={generationTab !== "render"}><label className="job-profile-select"><span>Render profile</span><select value={selectedProfileId} disabled={profileLocked || profiles.isLoading || profileMutation.isPending} onChange={(event) => setProfileSelections((current) => ({ ...current, [job.id]: event.target.value }))}><option value="" disabled>Select a render profile</option>{(profiles.data?.items ?? []).filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{profileChanged && <button className="job-action" type="button" disabled={!selectedProfileId || profileMutation.isPending} onClick={() => profileMutation.mutate({ jobId: job.id, profileId: selectedProfileId })}>{profileMutation.isPending ? "Saving…" : "Save render profile"}</button>}{profileLocked && <p className="field-hint">The render profile is locked while this job is active or completed.</p>}{renderAction}{!attempt && <p className="field-hint">No render attempt yet.</p>}{attempt && <div className="job-render-status"><strong>{attempt.provider} · {attempt.status.replaceAll("_", " ")}</strong><span>{renderProgressLabel(attempt)}</span><div className="job-render-identifiers"><InlineId label="Render attempt ID" value={attempt.id} />{attempt.external_job_id && <InlineId label="ComfyUI prompt ID" value={attempt.external_job_id} />}</div>{attempt.error_message && <p className="job-error" role="alert">{attempt.error_message}</p>}{attempt.assets.length > 0 ? <div className="job-output-list">{attempt.assets.map((asset) => <a className="button button-secondary" href={asset.download_url} download={asset.filename} key={asset.id}>Download {asset.filename}</a>)}</div> : <p className="field-hint">No output files yet.</p>}</div>}</div>
              </section>
            </div>
          </details>;
        }

        return <div className="job-row" key={job.id}>
          <span className="job-status-dot" />
          <span>
            <strong>{job.topic}</strong>
            <small>{job.status.replaceAll("_", " ")}</small>
            {failureMessage && <small className="job-error" role="alert">{failureMessage}</small>}
          </span>
          <b>{job.target_duration_seconds}s</b>
          {actions}
          {attempt && <small className="job-render-progress">
            {attempt.status.replaceAll("_", " ")} · {renderProgressLabel(attempt)}
          </small>}
        </div>
      })}
      {contentMutation.isError && <p className="form-error" role="alert">{contentMutation.error.message}</p>}
      {speechMutation.isError && <p className="form-error" role="alert">{speechMutation.error.message}</p>}
      {renderMutation.isError && <p className="form-error" role="alert">{renderMutation.error.message}</p>}
      {profileMutation.isError && <p className="form-error" role="alert">{profileMutation.error.message}</p>}
      {!nodes.isLoading && nodes.data?.items.length === 0 && <p className="field-hint">Add a ComfyUI render node in Settings before rendering.</p>}
    </div>
  );
}

export function RenderLibrary() {
  const attempts = useQuery({ queryKey: ["render-attempts"], queryFn: getRenderAttempts, refetchInterval: 5000 });
  const assets = attempts.data?.items.flatMap((attempt) => attempt.assets.map((asset) => ({ attempt, asset }))) ?? [];
  if (attempts.isLoading) return <div className="empty-state compact-empty"><p>Loading rendered videos…</p></div>;
  if (attempts.isError) return <div className="empty-state compact-empty"><p>Output library is unavailable.</p></div>;
  if (!assets.length) return <div className="empty-state compact-empty"><h3>No completed videos yet</h3><p>Render a content-ready job and its output will appear here.</p></div>;
  return <div className="render-library-grid">{assets.map(({ attempt, asset }) => <article className="render-library-card" key={asset.id}><div className="library-video-placeholder">▶</div><strong>{asset.filename}</strong><small>ComfyUI · {Math.round(asset.size_bytes / 1024)} KB</small><a className="button button-primary" href={asset.download_url} download={asset.filename}>Download video</a><span>Attempt {attempt.id}</span></article>)}</div>;
}
