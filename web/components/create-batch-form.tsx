"use client";

import React from "react";
import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createTopic, getRenderProfiles } from "@/lib/api";
import { Toast } from "@/components/feedback";

export function CreateTopicForm() {
  const queryClient = useQueryClient();
  const [topic, setTopic] = useState("");
  const [duration, setDuration] = useState("30");
  const [autoFit, setAutoFit] = useState(true);
  const [profileId, setProfileId] = useState("");
  const [toast, setToast] = useState<{ message: string; variant: "success" | "danger" } | null>(null);
  const profilesQuery = useQuery({
    queryKey: ["render-profiles"],
    queryFn: getRenderProfiles,
  });
  const availableProfiles = profilesQuery.data?.items.filter((profile) => profile.voice_profile_id !== null) ?? [];
  const mutation = useMutation({
    mutationFn: createTopic,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["topics"] });
      setTopic("");
      setToast({ message: "Topic created successfully.", variant: "success" });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (profilesQuery.isLoading) {
      setToast({ message: "Wait for render profiles to finish loading.", variant: "danger" });
      return;
    }
    if (profilesQuery.isError) {
      setToast({ message: "Render profiles are unavailable. Try again after reconnecting to the API.", variant: "danger" });
      return;
    }
    if (!availableProfiles.some((profile) => profile.id === profileId)) {
      setToast({ message: "Choose a render profile with a connected voice before creating a topic.", variant: "danger" });
      return;
    }
    mutation.mutate({
      topic: topic.trim(),
      render_profile_id: profileId,
      target_duration_seconds: Number(duration),
      auto_fit_duration: autoFit,
    });
  }

  return (
    <section className="panel create-form-panel" id="new-topic" aria-labelledby="new-topic-title">
      <div className="panel-heading">
        <div><h2 id="new-topic-title">Create a topic</h2><p>Start with one idea. You can generate as many content versions as you need.</p></div>
      </div>
      <form className="batch-form topic-form" onSubmit={submit}>
        <label className="topic-field">Topic<textarea required value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="Things that look like laziness but aren't: burnout" rows={4} /></label>
        <label>Render profile
          <select required value={profileId} onChange={(event) => setProfileId(event.target.value)} disabled={profilesQuery.isLoading || profilesQuery.isError}>
            <option value="">Choose a render profile…</option>
            {availableProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
          </select>
          {profilesQuery.isError ? <small className="field-hint">Render profiles could not be loaded.</small> : availableProfiles.length === 0 ? <small className="field-hint">Connect a voice to a render profile before creating a topic.</small> : null}
        </label>
        <div className="form-options">
          <label>Target duration (seconds)<input type="number" min="5" max="180" value={duration} onChange={(event) => setDuration(event.target.value)} /></label>
          <label className="checkbox-label"><input type="checkbox" checked={autoFit} onChange={(event) => setAutoFit(event.target.checked)} /> Auto-fit duration</label>
          <button className="button button-primary" type="submit" disabled={mutation.isPending || profilesQuery.isLoading || profilesQuery.isError || !availableProfiles.length || !profileId || !topic.trim()}>
            {mutation.isPending ? "Saving…" : "Create topic"}
          </button>
        </div>
        {mutation.isError && <p className="form-error" role="alert">{mutation.error.message}</p>}
      </form>
      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
    </section>
  );
}
