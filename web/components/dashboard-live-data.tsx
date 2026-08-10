"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { HumanDate } from "@/components/date-display";
import { ConfirmDialog } from "@/components/feedback";
import { deleteContent, deleteMediaAsset, deleteTopic, generateJobContent, generateJobSpeech, generateMoreContent, getBatches, getDashboardSummary, getRenderAttempts, getRenderNodes, getRenderProfiles, getTopicContents, getTopics, getVoiceProfiles, getWorkflowTemplates, queueJobRender, updateJobRenderProfile, updateJobVoiceProfile, updateJobWorkflowTemplate, uploadJobAudio } from "@/lib/api";
import type { DashboardSummary, Job, MediaAsset, RenderAttempt, TopicSummary } from "@/lib/api";

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
  if (job.status === "ready_to_render" && job.error_message?.trim()) {
    return `The latest speech generation failed: ${job.error_message.trim()} Your previous audio is still available.`;
  }
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
      <StatCard label="In progress" value={value("in_progress")} hint={hint ?? (data?.in_progress ? "Content is actively processing" : "No active content right now")} icon="◷" tone="blue" />
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

export function TopicHistory({ contentGenerationReady, speechGenerationReady }: { contentGenerationReady: boolean; speechGenerationReady: boolean }) {
  const queryClient = useQueryClient();
  const [topicOffset, setTopicOffset] = useState(0);
  const [openTopicIds, setOpenTopicIds] = useState<Record<string, boolean>>({});
  const [pendingTopicDelete, setPendingTopicDelete] = useState<TopicSummary | null>(null);
  const topicLimit = 20;
  const topics = useQuery({ queryKey: ["topics", topicOffset], queryFn: () => getTopics(topicLimit, topicOffset), refetchInterval: 5000 });
  useEffect(() => {
    if (!topics.isFetching && topics.data && topicOffset > 0 && topics.data.items.length === 0) {
      const lastOffset = Math.max(0, Math.floor(Math.max(0, topics.data.total - 1) / topicLimit) * topicLimit);
      setTopicOffset(lastOffset);
    }
  }, [topicOffset, topics.data, topics.isFetching]);
  const moreContent = useMutation({
    mutationFn: generateMoreContent,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["topics"] });
      void queryClient.invalidateQueries({ queryKey: ["topic-contents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
    },
  });
  const removeTopic = useMutation({
    mutationFn: deleteTopic,
    onSuccess: () => {
      setPendingTopicDelete(null);
      void queryClient.invalidateQueries({ queryKey: ["topics"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["render-attempts"] });
    },
  });

  if (topics.isLoading) return <div className="empty-state compact-empty"><p>Loading topic history…</p></div>;
  if (topics.isError) return <div className="empty-state compact-empty"><p>Topic history is temporarily unavailable.</p></div>;
  const topicItems = topics.data?.items ?? [];
  if (!topicItems.length && topicOffset > 0) return <div className="empty-state compact-empty"><p>Returning to the previous topic page…</p></div>;
  if (!topicItems.length) return <div className="empty-state compact-empty"><h3>No topics yet</h3><p>Create a topic to begin generating content.</p><a className="button button-secondary" href="#create">Create your first topic</a></div>;

  return <div className="topic-history-list">
    {topicItems.map((topic) => <details className="topic-history-card" key={topic.id} onToggle={(event) => { const open = event.currentTarget.open; setOpenTopicIds((current) => ({ ...current, [topic.id]: open })); }}>
      <summary>
        <span><strong>{topic.name}</strong><small>Created <HumanDate value={topic.created_at} /> · {topic.content_count} content {topic.content_count === 1 ? "version" : "versions"}</small></span>
        <span className="job-chevron" aria-hidden="true">⌄</span>
      </summary>
      <div className="topic-history-body">
        <div className="topic-history-actions">
          <button className="button button-primary button-small" type="button" disabled={!contentGenerationReady || moreContent.isPending} onClick={() => moreContent.mutate(topic.id)}>＋ {moreContent.isPending && moreContent.variables === topic.id ? "Generating…" : "Generate more content"}</button>
          <button className="icon-button danger" type="button" aria-label={`Delete topic ${topic.name}`} title="Delete topic" onClick={() => setPendingTopicDelete(topic)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg></button>
        </div>
        {!contentGenerationReady && <p className="field-hint">Configure OpenAI before generating more content.</p>}
        {openTopicIds[topic.id] && <TopicContents topic={topic} contentGenerationReady={contentGenerationReady} speechGenerationReady={speechGenerationReady} />}
      </div>
    </details>)}
    {topics.data && topics.data.total > topicLimit && <nav className="topic-history-pagination" aria-label="Topic history pages"><button className="button button-secondary button-small" type="button" disabled={topicOffset === 0} onClick={() => setTopicOffset((current) => Math.max(0, current - topicLimit))}>Previous</button><span>Topics {topicOffset + 1}–{Math.min(topicOffset + topicItems.length, topics.data.total)} of {topics.data.total}</span><button className="button button-secondary button-small" type="button" disabled={topicOffset + topicLimit >= topics.data.total} onClick={() => setTopicOffset((current) => current + topicLimit)}>Next</button></nav>}
    {moreContent.isError && <p className="form-error" role="alert">{moreContent.error.message}</p>}
    {removeTopic.isError && <p className="form-error" role="alert">{removeTopic.error.message}</p>}
    <ConfirmDialog open={pendingTopicDelete !== null} title="Delete this topic and all content?" message={pendingTopicDelete ? `“${pendingTopicDelete.name}” and all generated scripts, speech, render history, videos, and stored files will be permanently deleted.` : ""} confirmLabel="Delete topic" onCancel={() => setPendingTopicDelete(null)} onConfirm={() => { if (pendingTopicDelete) removeTopic.mutate(pendingTopicDelete.id); }} />
  </div>;
}

function TopicContents({ topic, contentGenerationReady, speechGenerationReady }: { topic: TopicSummary; contentGenerationReady: boolean; speechGenerationReady: boolean }) {
  const [contentOffset, setContentOffset] = useState(0);
  const contentLimit = 20;
  const contents = useQuery({ queryKey: ["topic-contents", topic.id, contentOffset], queryFn: () => getTopicContents(topic.id, contentLimit, contentOffset), refetchInterval: 5000 });
  useEffect(() => {
    if (!contents.isFetching && contents.data && contentOffset > 0 && contents.data.items.length === 0) {
      const lastOffset = Math.max(0, Math.floor(Math.max(0, contents.data.total - 1) / contentLimit) * contentLimit);
      setContentOffset(lastOffset);
    }
  }, [contentOffset, contents.data, contents.isFetching]);
  if (contents.isLoading) return <div className="empty-state compact-empty"><p>Loading content history…</p></div>;
  if (contents.isError) return <p className="form-error" role="alert">Content history is temporarily unavailable.</p>;
  const items = contents.data?.items ?? [];
  if (!items.length && contentOffset > 0) return <div className="empty-state compact-empty"><p>Returning to the previous content page…</p></div>;
  return <>
    <RecentJobs contentGenerationReady={contentGenerationReady} speechGenerationReady={speechGenerationReady} detailed jobsOverride={items} topicNameOverride={topic.name} contentTotal={contents.data?.total} />
    {contents.data && contents.data.total > contentLimit && <nav className="topic-history-pagination" aria-label={`Content history pages for ${topic.name}`}><button className="button button-secondary button-small" type="button" disabled={contentOffset === 0} onClick={() => setContentOffset((current) => Math.max(0, current - contentLimit))}>Previous content</button><span>Content {contentOffset + 1}–{Math.min(contentOffset + items.length, contents.data.total)} of {contents.data.total}</span><button className="button button-secondary button-small" type="button" disabled={contentOffset + contentLimit >= contents.data.total} onClick={() => setContentOffset((current) => current + contentLimit)}>Next content</button></nav>}
  </>;
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
  return <><button className="job-id-icon job-id-toggle" type="button" aria-label={`${visible ? "Hide" : "Show"} ${label}`} title={`${visible ? "Hide" : "Show"} ${label}`} onClick={() => setVisible((current) => !current)}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="8" cy="11" r="2" /><path d="M5.5 16c.7-1.5 1.5-2 2.5-2s1.8.5 2.5 2M13 9h5m-5 4h5" /></svg></button>{visible && <div className="job-inline-id-value"><code>{value}</code><button className="job-id-icon" type="button" aria-label={`Copy ${label}`} title={`Copy ${label}`} onClick={copy}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg></button>{copied && <span role="status">Copied</span>}</div>}</>;
}

type ContentTab = "script" | "instagram" | "tiktok";
type GenerationTab = "speech" | "render";
const ACTIVE_JOB_STATUSES: Job["status"][] = ["generating_content", "generating_tts", "fitting_duration", "queued", "submitting_render", "rendering", "downloading_output"];

function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const encoded = typeof reader.result === "string" ? reader.result.split(",", 2)[1] : null;
      if (encoded) resolve(encoded);
      else reject(new Error("The audio file could not be encoded."));
    };
    reader.onerror = () => reject(new Error("The audio file could not be read."));
    reader.readAsDataURL(file);
  });
}

export function RecentJobs({ contentGenerationReady, speechGenerationReady, detailed = false, jobsOverride, topicNameOverride, contentTotal }: { contentGenerationReady: boolean; speechGenerationReady: boolean; detailed?: boolean; jobsOverride?: Job[]; topicNameOverride?: string; contentTotal?: number }) {
  const queryClient = useQueryClient();
  const [contentTabs, setContentTabs] = useState<Record<string, ContentTab>>({});
  const [generationTabs, setGenerationTabs] = useState<Record<string, GenerationTab>>({});
  const [profileSelections, setProfileSelections] = useState<Record<string, string>>({});
  const [voiceSelections, setVoiceSelections] = useState<Record<string, string>>({});
  const [workflowSelections, setWorkflowSelections] = useState<Record<string, string>>({});
  const [previewVideoIds, setPreviewVideoIds] = useState<Record<string, boolean>>({});
  const [pendingVideoDelete, setPendingVideoDelete] = useState<MediaAsset | null>(null);
  const [pendingContentDelete, setPendingContentDelete] = useState<Job | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
    refetchInterval: 5000,
    enabled: jobsOverride === undefined,
  });
  const nodes = useQuery({ queryKey: ["render-nodes"], queryFn: getRenderNodes });
  const attempts = useQuery({ queryKey: ["render-attempts"], queryFn: getRenderAttempts, refetchInterval: 5000 });
  const batches = useQuery({ queryKey: ["batches"], queryFn: getBatches, enabled: detailed && jobsOverride === undefined });
  const profiles = useQuery({ queryKey: ["render-profiles"], queryFn: getRenderProfiles, enabled: detailed });
  const voices = useQuery({ queryKey: ["voice-profiles"], queryFn: getVoiceProfiles, enabled: detailed });
  const workflows = useQuery({ queryKey: ["workflow-templates"], queryFn: getWorkflowTemplates, enabled: detailed });
  const updateCachedJob = (updatedJob: Job) => {
    queryClient.setQueryData<DashboardSummary>(["dashboard-summary"], (current) => current ? {
      ...current,
      recent_jobs: current.recent_jobs.map((job) => job.id === updatedJob.id ? updatedJob : job),
    } : current);
  };
  const refreshContent = () => {
    void queryClient.invalidateQueries({ queryKey: ["topics"] });
    void queryClient.invalidateQueries({ queryKey: ["topic-contents"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
  };
  const clearSelection = (setter: React.Dispatch<React.SetStateAction<Record<string, string>>>, jobId: string) => {
    setter((current) => {
      const next = { ...current };
      delete next[jobId];
      return next;
    });
  };
  const contentMutation = useMutation({
    mutationFn: generateJobContent,
    onSuccess: refreshContent,
  });
  const speechMutation = useMutation({
    mutationFn: generateJobSpeech,
    onSuccess: refreshContent,
  });
  const renderMutation = useMutation({
    mutationFn: ({ jobId, nodeId }: { jobId: string; nodeId: string }) => queueJobRender(jobId, nodeId),
    onSuccess: () => {
      refreshContent();
      void queryClient.invalidateQueries({ queryKey: ["render-attempts"] });
    },
  });
  const profileMutation = useMutation({
    mutationFn: ({ jobId, profileId }: { jobId: string; profileId: string }) => updateJobRenderProfile(jobId, profileId),
    onSuccess: (updatedJob) => {
      updateCachedJob(updatedJob);
      clearSelection(setProfileSelections, updatedJob.id);
      clearSelection(setVoiceSelections, updatedJob.id);
      clearSelection(setWorkflowSelections, updatedJob.id);
      refreshContent();
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
  });
  const voiceMutation = useMutation({
    mutationFn: ({ jobId, voiceProfileId }: { jobId: string; voiceProfileId: string }) => updateJobVoiceProfile(jobId, voiceProfileId),
    onSuccess: (updatedJob) => {
      updateCachedJob(updatedJob);
      clearSelection(setVoiceSelections, updatedJob.id);
      refreshContent();
    },
  });
  const workflowMutation = useMutation({
    mutationFn: ({ jobId, workflowTemplateId }: { jobId: string; workflowTemplateId: string }) => updateJobWorkflowTemplate(jobId, workflowTemplateId),
    onSuccess: (updatedJob) => {
      updateCachedJob(updatedJob);
      clearSelection(setWorkflowSelections, updatedJob.id);
      refreshContent();
    },
  });
  const audioMutation = useMutation({
    mutationFn: async ({ jobId, file }: { jobId: string; file: File }) => uploadJobAudio(jobId, {
      filename: file.name,
      content_base64: await readFileBase64(file),
      content_type: file.type || "audio/mpeg",
    }),
    onSuccess: (updatedJob) => {
      updateCachedJob(updatedJob);
      refreshContent();
    },
  });
  const videoDeleteMutation = useMutation({
    mutationFn: deleteMediaAsset,
    onSuccess: () => {
      setPendingVideoDelete(null);
      refreshContent();
      void queryClient.invalidateQueries({ queryKey: ["render-attempts"] });
    },
  });
  const contentDeleteMutation = useMutation({
    mutationFn: deleteContent,
    onSuccess: () => {
      setPendingContentDelete(null);
      void queryClient.invalidateQueries({ queryKey: ["topics"] });
      void queryClient.invalidateQueries({ queryKey: ["topic-contents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["render-attempts"] });
    },
  });
  const jobs = jobsOverride ?? data?.recent_jobs ?? [];

  if (jobsOverride === undefined && isLoading) {
    return <div className="empty-state compact-empty"><p>Loading recent content…</p></div>;
  }
  if (jobsOverride === undefined && isError) {
    return <div className="empty-state compact-empty"><p>Recent content is temporarily unavailable.</p></div>;
  }
  if (jobs.length === 0) {
    return (
      <div className="empty-state compact-empty">
        <div className="empty-icon">◷</div>
        <h3>No content yet</h3>
        <p>Your generated scripts, speech, and videos will show up here.</p>
        <a className="button button-secondary" href="#create">Create your first topic</a>
      </div>
    );
  }

  return (
    <div className="jobs-list">
      {jobs.map((job) => {
        const jobAttempts = attempts.data?.items.filter((item) => item.job_id === job.id) ?? [];
        const attempt = jobAttempts[0];
        const failedContent = failedJobRetryKind(job, attempt) === "content";
        const failedRender = failedJobRetryKind(job, attempt) === "render";
        const failedSpeech = failedJobRetryKind(job, attempt) === "tts";
        const failureMessage = jobFailureMessage(job);
        const canRender = job.status === "tts_ready" || job.status === "ready_to_render" || job.status === "completed" || failedRender;
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
          {(job.status === "content_ready" || job.status === "tts_ready" || job.status === "ready_to_render" || job.status === "completed" || failedSpeech) && (
            <button
              className="job-action"
              type="button"
              disabled={speechMutation.isPending || !speechGenerationReady}
              title={speechGenerationReady ? undefined : "Set ELEVENLABS_API_KEY in the root .env file and restart Docker"}
              onClick={() => speechMutation.mutate(job.id)}
            >
              {speechMutation.isPending && speechMutation.variables === job.id ? "Queuing…" : speechGenerationReady ? failedSpeech ? "Retry speech" : job.audio_asset ? "Generate audio again" : "Generate speech" : "ElevenLabs setup required"}
            </button>
          )}
        </>;
        const renderAction = <>
          {canRender && (
            <button className="job-action" type="button" disabled={renderMutation.isPending || !nodes.data?.items.some((node) => node.is_active)} onClick={() => { const node = nodes.data?.items.find((item) => item.health_status === "healthy") ?? nodes.data?.items.find((item) => item.is_active); if (node) renderMutation.mutate({ jobId: job.id, nodeId: node.id }); }}>{renderMutation.isPending && renderMutation.variables?.jobId === job.id ? "Queuing render…" : failedRender ? "Retry render" : job.status === "completed" ? "Generate new video" : "Render with ComfyUI"}</button>
          )}
        </>;
        const actions = <>{contentAction}{speechAction}{renderAction}</>;

        if (detailed) {
          const hasGeneratedContent = Boolean(job.speech_script || job.hook || job.instagram_metadata || job.tiktok_metadata);
          const contentTab = contentTabs[job.id] ?? "script";
          const generationTab = generationTabs[job.id] ?? "speech";
          const batchName = topicNameOverride ?? batches.data?.items?.find((batch) => batch.id === job.batch_id)?.name ?? (batches.isLoading ? "Loading topic…" : "Topic unavailable");
          const profile = profiles.data?.items?.find((item) => item.id === job.render_profile_id);
          const profileName = profile?.name ?? (profiles.isLoading ? "Loading profile…" : job.render_profile_id ? "Unavailable profile" : "Not assigned");
          const selectedProfileId = profileSelections[job.id] ?? job.render_profile_id ?? "";
          const profileChanged = selectedProfileId !== (job.render_profile_id ?? "");
          const profileLocked = ["queued", "submitting_render", "rendering", "downloading_output"].includes(job.status);
          const effectiveVoiceId = job.voice_profile_id ?? profile?.voice_profile_id ?? "";
          const selectedVoiceId = voiceSelections[job.id] ?? effectiveVoiceId;
          const voiceChanged = selectedVoiceId !== effectiveVoiceId;
          const voiceLocked = ["generating_tts", "queued", "submitting_render", "rendering", "downloading_output"].includes(job.status);
          const effectiveWorkflowId = job.workflow_template_id ?? profile?.workflow_template_id ?? "";
          const selectedWorkflowId = workflowSelections[job.id] ?? effectiveWorkflowId;
          const workflowChanged = selectedWorkflowId !== effectiveWorkflowId;
          const selectedWorkflow = workflows.data?.items?.find((item) => item.id === selectedWorkflowId);
          return <details className="job-card" key={job.id}>
            <summary className="job-card-summary">
              <span className="job-status-dot" />
              <span className="job-card-title"><strong>Content {job.content_number}{job.hook ? ` · ${job.hook}` : ""}</strong><small><span>Topic: {batchName}</span><span>Render: {profileName}</span><span>{job.status.replaceAll("_", " ")} · Updated <HumanDate value={job.updated_at} /></span></small></span>
              <b>{job.target_duration_seconds}s</b>
              {attempt && <small className="job-render-progress">{attempt.status.replaceAll("_", " ")} · {renderProgressLabel(attempt)}</small>}
              <span className="job-chevron" aria-hidden="true">⌄</span>
            </summary>
            <div className="job-card-details">
              <div className="job-context"><div><span>Content</span><div className="job-name-with-id"><strong>Content {job.content_number}</strong><InlineId label="Content ID" value={job.id} /></div></div><div><span>Topic</span><div className="job-name-with-id"><strong>{batchName}</strong><InlineId label="Topic ID" value={job.batch_id} /></div></div><div><span>Render profile</span><div className="job-name-with-id"><strong>{profileName}</strong>{job.render_profile_id && <InlineId label="Render profile ID" value={job.render_profile_id} />}</div></div><div><span>Content model</span><strong>{job.llm_provider && job.llm_model ? `${job.llm_provider} · ${job.llm_model}` : "Not generated"}</strong></div></div>
              <div className="content-record-actions"><span>Content created <HumanDate value={job.created_at} /></span><button className="job-media-icon danger" type="button" aria-label={`Delete content ${job.id}`} title={contentTotal === 1 ? "Delete the topic to remove its only content" : "Delete content and all files"} disabled={ACTIVE_JOB_STATUSES.includes(job.status) || contentTotal === 1} onClick={() => setPendingContentDelete(job)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg></button></div>
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
                <div className="job-generation-panel" role="tabpanel" hidden={generationTab !== "speech"}>
                  <div className="job-generation-selector"><label><span>Voice profile</span><select value={selectedVoiceId} disabled={voiceLocked || voices.isLoading || voiceMutation.isPending} onChange={(event) => setVoiceSelections((current) => ({ ...current, [job.id]: event.target.value }))}><option value="" disabled>Select a voice profile</option>{voices.data?.items?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{selectedVoiceId && <Link className="job-detail-link" href={`/voice-profiles#voice-profile-${selectedVoiceId}`} aria-label="Open voice profile details" title="Open voice profile details"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5v5M19 5l-9 9M19 14v5H5V5h5" /></svg></Link>}</div>
                  {voiceChanged && <button className="job-action" type="button" disabled={!selectedVoiceId || voiceMutation.isPending} onClick={() => voiceMutation.mutate({ jobId: job.id, voiceProfileId: selectedVoiceId })}>{voiceMutation.isPending ? "Saving…" : "Save voice profile"}</button>}
                  {voiceLocked && <p className="field-hint">The voice profile is locked while speech or video is active.</p>}
                  <p className="field-hint">Create ElevenLabs speech from the generated script. Generate again to keep another version.</p>{speechAction}<div className="job-audio-history">{(job.audio_assets?.length ? job.audio_assets : job.audio_asset ? [job.audio_asset] : []).map((asset, index) => <div className="job-audio-result" key={asset.id}><span>{asset.filename}</span>{asset.generation_metadata?.source === "tts" && <small>{[asset.generation_metadata.provider, asset.generation_metadata.voice_id, asset.generation_metadata.model].filter(Boolean).join(" · ")}</small>}<audio controls preload="none" src={`${asset.download_url}?inline=true`}>Your browser does not support audio playback.</audio><a className="voice-preview-download" href={asset.download_url} download={asset.filename} aria-label={index === 0 ? "Download generated speech" : `Download ${asset.filename}`} title="Download audio"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M5 21h14" /></svg></a></div>)}</div>
                </div>
                <div className="job-generation-panel" role="tabpanel" hidden={generationTab !== "render"}>
                  <div className="job-generation-selector"><label><span>Render profile</span><select value={selectedProfileId} disabled={profileLocked || profiles.isLoading || profileMutation.isPending} onChange={(event) => setProfileSelections((current) => ({ ...current, [job.id]: event.target.value }))}><option value="" disabled>Select a render profile</option>{(profiles.data?.items ?? []).filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div>
                  {profileChanged && <button className="job-action" type="button" disabled={!selectedProfileId || profileMutation.isPending} onClick={() => profileMutation.mutate({ jobId: job.id, profileId: selectedProfileId })}>{profileMutation.isPending ? "Saving…" : "Save render profile"}</button>}
                  <div className="job-generation-selector"><label><span>Workflow</span><select value={selectedWorkflowId} disabled={profileLocked || workflows.isLoading || workflowMutation.isPending} onChange={(event) => setWorkflowSelections((current) => ({ ...current, [job.id]: event.target.value }))}><option value="" disabled>Select a workflow</option>{workflows.data?.items?.filter((item) => item.renderer_provider === "comfyui").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{selectedWorkflow && <Link className="job-detail-link" href={`/workflows#workflow-${selectedWorkflow.id}`} aria-label="Open workflow details" title="Open workflow details"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5h5v5M19 5l-9 9M19 14v5H5V5h5" /></svg></Link>}</div>
                  {workflowChanged && <button className="job-action" type="button" disabled={!selectedWorkflowId || workflowMutation.isPending} onClick={() => workflowMutation.mutate({ jobId: job.id, workflowTemplateId: selectedWorkflowId })}>{workflowMutation.isPending ? "Saving…" : "Save workflow"}</button>}
                  <div className="job-render-audio"><strong>Render audio</strong>{job.audio_asset ? <><span>{job.audio_asset.filename}</span><audio controls preload="metadata" src={`${job.audio_asset.download_url}?inline=true`}>Your browser does not support audio playback.</audio></> : <span>No speech file selected.</span>}<label className="job-upload-audio"><input type="file" accept="audio/*" aria-label="Upload different audio" disabled={profileLocked || audioMutation.isPending} onChange={(event) => { const file = event.target.files?.[0]; if (file) audioMutation.mutate({ jobId: job.id, file }); event.target.value = ""; }} /><span>{audioMutation.isPending && audioMutation.variables?.jobId === job.id ? "Uploading…" : "Upload different audio"}</span></label></div>
                  {profileLocked && <p className="field-hint">Render settings are locked while this content is active.</p>}{renderAction}{!attempt && <p className="field-hint">No render attempt yet.</p>}{jobAttempts.map((renderAttempt) => <div className="job-render-status" key={renderAttempt.id}><div className="job-name-with-id job-render-name"><strong>{renderAttempt.provider} · {renderAttempt.status.replaceAll("_", " ")}</strong>{renderAttempt.external_job_id && <InlineId label="ComfyUI Job ID" value={renderAttempt.external_job_id} />}</div><span>{renderProgressLabel(renderAttempt)}</span>{renderAttempt.error_message && <p className="job-error" role="alert">{renderAttempt.error_message}</p>}{renderAttempt.assets.length > 0 ? <div className="job-output-list">{renderAttempt.assets.map((asset) => <div className="job-video-output" key={asset.id}><span>{asset.filename}</span><div className="job-video-actions"><button className="job-media-icon" type="button" aria-label={`Preview ${asset.filename}`} title="Preview video" onClick={() => setPreviewVideoIds((current) => ({ ...current, [asset.id]: !current[asset.id] }))}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7Z" /></svg></button><a className="job-media-icon" href={asset.download_url} download={asset.filename} aria-label={`Download ${asset.filename}`} title="Download video"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M5 21h14" /></svg></a><button className="job-media-icon danger" type="button" aria-label={`Delete ${asset.filename}`} title={profileLocked ? "Video deletion is locked while a rerender is active" : "Delete video"} disabled={profileLocked} onClick={() => setPendingVideoDelete(asset)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg></button></div>{previewVideoIds[asset.id] && <video controls preload="metadata" src={`${asset.download_url}?inline=true`}>Your browser does not support video playback.</video>}</div>)}</div> : <p className="field-hint">No output files yet.</p>}</div>)}
                </div>
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
      {voiceMutation.isError && <p className="form-error" role="alert">{voiceMutation.error.message}</p>}
      {workflowMutation.isError && <p className="form-error" role="alert">{workflowMutation.error.message}</p>}
      {audioMutation.isError && <p className="form-error" role="alert">{audioMutation.error.message}</p>}
      {videoDeleteMutation.isError && <p className="form-error" role="alert">{videoDeleteMutation.error.message}</p>}
      {contentDeleteMutation.isError && <p className="form-error" role="alert">{contentDeleteMutation.error.message}</p>}
      {!nodes.isLoading && nodes.data?.items.length === 0 && <p className="field-hint">Add a ComfyUI render node in Settings before rendering.</p>}
      <ConfirmDialog open={pendingVideoDelete !== null} title="Delete generated video?" message={pendingVideoDelete ? `“${pendingVideoDelete.filename}” will be permanently removed from media storage. The job will become ready to render again.` : ""} confirmLabel="Delete" onCancel={() => setPendingVideoDelete(null)} onConfirm={() => { if (pendingVideoDelete) videoDeleteMutation.mutate(pendingVideoDelete.id); }} />
      <ConfirmDialog open={pendingContentDelete !== null} title="Delete this content and all files?" message={pendingContentDelete ? "The script, speech, render attempts, videos, and every stored file for this content version will be permanently deleted." : ""} confirmLabel="Delete content" onCancel={() => setPendingContentDelete(null)} onConfirm={() => { if (pendingContentDelete) contentDeleteMutation.mutate(pendingContentDelete.id); }} />
    </div>
  );
}

export function RenderLibrary() {
  const attempts = useQuery({ queryKey: ["render-attempts"], queryFn: getRenderAttempts, refetchInterval: 5000 });
  const assets = attempts.data?.items.flatMap((attempt) => attempt.assets.map((asset) => ({ attempt, asset }))) ?? [];
  if (attempts.isLoading) return <div className="empty-state compact-empty"><p>Loading rendered videos…</p></div>;
  if (attempts.isError) return <div className="empty-state compact-empty"><p>Output library is unavailable.</p></div>;
  if (!assets.length) return <div className="empty-state compact-empty"><h3>No completed videos yet</h3><p>Render content with prepared speech and its output will appear here.</p></div>;
  return <div className="render-library-grid">{assets.map(({ attempt, asset }) => <article className="render-library-card" key={asset.id}><div className="library-video-placeholder">▶</div><strong>{asset.filename}</strong><small>ComfyUI · {Math.round(asset.size_bytes / 1024)} KB</small><a className="button button-primary" href={asset.download_url} download={asset.filename}>Download video</a><span>Attempt {attempt.id}</span></article>)}</div>;
}
