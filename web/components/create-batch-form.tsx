"use client";

import React from "react";
import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createTopic, createTopics, getRenderProfiles } from "@/lib/api";
import { Toast } from "@/components/feedback";

export function CreateTopicForm() {
  const queryClient = useQueryClient();
  const [topics, setTopics] = useState([""]);
  const [duration, setDuration] = useState("30");
  const [autoFit, setAutoFit] = useState(true);
  const [profileId, setProfileId] = useState("");
  const [toast, setToast] = useState<{ message: string; variant: "success" | "danger" } | null>(null);
  const profilesQuery = useQuery({
    queryKey: ["render-profiles"],
    queryFn: getRenderProfiles,
  });
  const availableProfiles = profilesQuery.data?.items.filter((profile) => profile.is_active && profile.voice_profile_id !== null) ?? [];
  const mutation = useMutation({
    mutationFn: async () => {
      const cleanedTopics = topics.map((topic) => topic.trim()).filter(Boolean);
      const shared = {
        render_profile_id: profileId,
        target_duration_seconds: Number(duration),
        auto_fit_duration: autoFit,
      };
      return cleanedTopics.length === 1
        ? createTopic({ topic: cleanedTopics[0], ...shared })
        : createTopics({ topics: cleanedTopics, ...shared });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["topics"] });
      const createdCount = topics.filter((topic) => topic.trim()).length;
      setTopics([""]);
      setToast({ message: createdCount === 1 ? "Topic created successfully." : `${createdCount} topics created successfully.`, variant: "success" });
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
    mutation.mutate();
  }

  return (
    <section className="panel create-form-panel" id="new-topic" aria-labelledby="new-topic-title">
      <div className="panel-heading">
        <div><h2 id="new-topic-title">Create a topic</h2><p>Start with one idea. You can generate as many content versions as you need.</p></div>
      </div>
      <form className="batch-form topic-form" onSubmit={submit}>
        <div className="topic-input-list">
          {topics.map((topic, index) => <div className="topic-input-row" key={index}>
            <label className="topic-field">{topics.length === 1 ? "Topic" : `Topic ${index + 1}`}<textarea required value={topic} onChange={(event) => setTopics((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} placeholder="Things that look like laziness but aren't: burnout" rows={4} /></label>
            {topics.length > 1 && <button className="icon-button danger topic-remove" type="button" aria-label={`Remove topic ${index + 1}`} title="Remove topic" onClick={() => setTopics((current) => current.filter((_, itemIndex) => itemIndex !== index))}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg></button>}
          </div>)}
          <button className="button button-secondary add-topic-button" type="button" aria-label="Add another topic" onClick={() => setTopics((current) => [...current, ""])}>＋ Add another topic</button>
        </div>
        <label>Render profile
          <select required value={profileId} onChange={(event) => setProfileId(event.target.value)} disabled={profilesQuery.isLoading || profilesQuery.isError}>
            <option value="">Choose a render profile…</option>
            {availableProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
          </select>
          {profilesQuery.isError ? <small className="field-hint">Render profiles could not be loaded.</small> : availableProfiles.length === 0 ? <small className="field-hint">Create an active render profile with a connected voice before creating a topic.</small> : null}
        </label>
        <div className="form-options">
          <label>Target duration (seconds)<input type="number" min="5" max="180" value={duration} onChange={(event) => setDuration(event.target.value)} /></label>
          <label className="checkbox-label"><input type="checkbox" checked={autoFit} onChange={(event) => setAutoFit(event.target.checked)} /> Auto-fit duration</label>
          <button className="button button-primary" type="submit" disabled={mutation.isPending || profilesQuery.isLoading || profilesQuery.isError || !availableProfiles.length || !profileId || topics.some((topic) => !topic.trim())}>
            {mutation.isPending ? "Saving…" : topics.length === 1 ? "Create topic" : `Create ${topics.length} topics`}
          </button>
        </div>
        {mutation.isError && <p className="form-error" role="alert">{mutation.error.message}</p>}
      </form>
      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
    </section>
  );
}
