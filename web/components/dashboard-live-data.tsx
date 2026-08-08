"use client";

import React, { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { generateJobContent, getDashboardSummary } from "@/lib/api";

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

export function RecentJobs() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
    refetchInterval: 5000,
  });
  const contentMutation = useMutation({
    mutationFn: generateJobContent,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
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
      {jobs.map((job) => (
        <div className="job-row" key={job.id}>
          <span className="job-status-dot" />
          <span><strong>{job.topic}</strong><small>{job.status.replaceAll("_", " ")}</small></span>
          <b>{job.target_duration_seconds}s</b>
          {(job.status === "draft" || job.status === "failed") && (
            <button
              className="job-action"
              type="button"
              disabled={contentMutation.isPending}
              onClick={() => contentMutation.mutate(job.id)}
            >
              {contentMutation.isPending && contentMutation.variables === job.id ? "Queuing…" : "Generate content"}
            </button>
          )}
        </div>
      ))}
      {contentMutation.isError && <p className="form-error" role="alert">{contentMutation.error.message}</p>}
    </div>
  );
}
