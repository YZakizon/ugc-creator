"use client";

import React, { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog, Toast } from "@/components/feedback";
import { HumanDate } from "@/components/date-display";
import {
  createRenderProfileSetup,
  deleteRenderProfile,
  getCharacters,
  getRenderProfiles,
  getVoiceProfiles,
  getWorkflowTemplates,
  updateRenderProfile,
} from "@/lib/api";
import type { RenderProfile } from "@/lib/api";

export function RenderProfileSetup() {
  const queryClient = useQueryClient();
  const profilesQuery = useQuery({ queryKey: ["render-profiles"], queryFn: getRenderProfiles });
  const workflowsQuery = useQuery({ queryKey: ["workflow-templates"], queryFn: getWorkflowTemplates });
  const charactersQuery = useQuery({ queryKey: ["characters"], queryFn: getCharacters });
  const voicesQuery = useQuery({ queryKey: ["voice-profiles"], queryFn: getVoiceProfiles });
  const [characterName, setCharacterName] = useState("");
  const [voiceProfileId, setVoiceProfileId] = useState("");
  const [profileName, setProfileName] = useState("");
  const [workflowTemplateId, setWorkflowTemplateId] = useState("");
  const [expandedProfileId, setExpandedProfileId] = useState<string | null>(null);
  const [editProfileName, setEditProfileName] = useState("");
  const [editCharacterName, setEditCharacterName] = useState("");
  const [editVoiceProfileId, setEditVoiceProfileId] = useState("");
  const [editWorkflowTemplateId, setEditWorkflowTemplateId] = useState("");
  const [activeTab, setActiveTab] = useState<"create" | "list">("list");
  const [pendingDelete, setPendingDelete] = useState<RenderProfile | null>(null);
  const [toast, setToast] = useState<{ message: string; variant: "success" | "danger" } | null>(null);
  const profileDependenciesUnavailable = workflowsQuery.isLoading || workflowsQuery.isError
    || voicesQuery.isLoading || voicesQuery.isError;
  const mutation = useMutation({
    mutationFn: () => createRenderProfileSetup({
      profile_name: profileName.trim(),
      character_name: characterName.trim(),
      voice_profile_id: voiceProfileId,
      renderer_provider: "comfyui",
      workflow_template_id: workflowTemplateId || undefined,
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["render-profiles"] });
      void queryClient.invalidateQueries({ queryKey: ["characters"] });
      void queryClient.invalidateQueries({ queryKey: ["voice-profiles"] });
      setCharacterName("");
      setVoiceProfileId("");
      setProfileName("");
      setWorkflowTemplateId("");
      setActiveTab("list");
      setToast({ message: "Render profile created successfully.", variant: "success" });
    },
  });
  const updateMutation = useMutation({
    mutationFn: updateRenderProfile,
    onSuccess: (profile) => {
      void queryClient.invalidateQueries({ queryKey: ["render-profiles"] });
      void queryClient.invalidateQueries({ queryKey: ["characters"] });
      void queryClient.invalidateQueries({ queryKey: ["voice-profiles"] });
      setEditProfileName(profile.name);
      setEditWorkflowTemplateId(profile.workflow_template_id ?? "");
      setToast({ message: "Profile updated successfully.", variant: "success" });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: deleteRenderProfile,
    onSuccess: (_, profileId) => {
      void queryClient.invalidateQueries({ queryKey: ["render-profiles"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] });
      if (expandedProfileId === profileId) setExpandedProfileId(null);
      setToast({ message: "Profile deleted.", variant: "success" });
    },
    onError: (error) => setToast({ message: error.message, variant: "danger" }),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (profileDependenciesUnavailable || !workflowTemplateId || !voiceProfileId) {
      setToast({ message: "Wait until workflows and voice profiles are available, then select both before creating a profile.", variant: "danger" });
      return;
    }
    mutation.mutate();
  }

  useEffect(() => {
    function openHashTarget() {
      if (["#new-profile", "#create-profile", "#characters"].includes(window.location.hash)) {
        setActiveTab("create");
      } else if (window.location.hash.startsWith("#profile-")) {
        setActiveTab("list");
      }
    }
    openHashTarget();
    window.addEventListener("hashchange", openHashTarget);
    return () => window.removeEventListener("hashchange", openHashTarget);
  }, []);

  useEffect(() => {
    const profileId = window.location.hash.startsWith("#profile-")
      ? window.location.hash.slice("#profile-".length)
      : "";
    if (!profileId) return;
    const profile = profilesQuery.data?.items.find((item) => item.id === profileId);
    if (!profile) return;
    setExpandedProfileId(profile.id);
    setEditProfileName(profile.name);
    setEditCharacterName(charactersQuery.data?.items.find((item) => item.id === profile.character_id)?.name ?? "");
    setEditVoiceProfileId(profile.voice_profile_id ?? "");
    setEditWorkflowTemplateId(profile.workflow_template_id ?? "");
    window.requestAnimationFrame(() => document.getElementById(`profile-details-${profile.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, [charactersQuery.data, profilesQuery.data]);

  function toggleProfile(profile: RenderProfile) {
    if (expandedProfileId === profile.id) {
      setExpandedProfileId(null);
      updateMutation.reset();
      return;
    }
    setExpandedProfileId(profile.id);
    setEditProfileName(profile.name);
    setEditCharacterName(charactersQuery.data?.items.find((item) => item.id === profile.character_id)?.name ?? "");
    setEditVoiceProfileId(profile.voice_profile_id ?? "");
    setEditWorkflowTemplateId(profile.workflow_template_id ?? "");
    updateMutation.reset();
  }

  function submitEdit(event: FormEvent<HTMLFormElement>, profileId: string) {
    event.preventDefault();
    if (workflowsQuery.isLoading || workflowsQuery.isError || voicesQuery.isLoading || voicesQuery.isError) {
      setToast({ message: "Profile dependencies are unavailable. Your existing workflow and voice were not changed.", variant: "danger" });
      return;
    }
    updateMutation.mutate({ id: profileId, name: editProfileName.trim(), character_name: editCharacterName.trim(), voice_profile_id: editVoiceProfileId || null, workflow_template_id: editWorkflowTemplateId || undefined });
  }

  return (
    <div className="profile-setup">
      <div className="profile-tabs" role="tablist" aria-label="Profile sections">
        <button id="profile-tab-create-button" className={`profile-tab${activeTab === "create" ? " active" : ""}`} type="button" role="tab" aria-selected={activeTab === "create"} aria-controls="profile-tab-create" onClick={() => setActiveTab("create")}>Create profile</button>
        <button id="profile-tab-list-button" className={`profile-tab${activeTab === "list" ? " active" : ""}`} type="button" role="tab" aria-selected={activeTab === "list"} aria-controls="profile-tab-list" onClick={() => setActiveTab("list")}>Profiles</button>
      </div>

      <div id="profile-tab-list" className="profile-tab-panel" role="tabpanel" aria-labelledby="profile-tab-list-button" hidden={activeTab !== "list"}>
      {profilesQuery.isLoading ? (
        <div className="profile-empty compact-profile-empty"><p>Loading profiles…</p></div>
      ) : profilesQuery.isError ? (
        <div className="profile-empty compact-profile-empty"><p className="form-error" role="alert">Profiles are unavailable: {profilesQuery.error.message}</p></div>
      ) : profilesQuery.data?.items.length ? (
        <div className="profile-list" aria-label="Saved profiles">
          {profilesQuery.data.items.map((profile) => {
            const isExpanded = expandedProfileId === profile.id;
            const workflow = workflowsQuery.data?.items.find((item) => item.id === profile.workflow_template_id);
            return <article className={`saved-profile saved-profile-collapsible${isExpanded ? " expanded" : ""}`} key={profile.id}>
              <div className="saved-profile-header">
                <button className="saved-profile-toggle" type="button" aria-label={`${isExpanded ? "Hide" : "Show"} ${profile.name} details`} aria-expanded={isExpanded} aria-controls={`profile-details-${profile.id}`} onClick={() => toggleProfile(profile)}>
                  <span className="profile-list-icon">✦</span>
                  <span className="saved-profile-summary"><strong>{profile.name}</strong><small>Created <HumanDate value={profile.created_at} /> · Updated <HumanDate value={profile.updated_at} /></small></span>
                  <svg className="profile-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5" /></svg>
                </button>
                <button className="icon-button profile-icon-button danger" type="button" aria-label={`Delete ${profile.name}`} title="Delete profile" disabled={deleteMutation.isPending} onClick={() => setPendingDelete(profile)}>
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg>
                </button>
              </div>
              {isExpanded && <div id={`profile-details-${profile.id}`} className="saved-profile-details">
                <form className="profile-inline-form" onSubmit={(event) => submitEdit(event, profile.id)}>
                  <div className="profile-edit-heading"><div><h3>Profile configuration</h3><p>Click a field value to edit it, then save your changes.</p></div><span className={`profile-status${profile.is_active ? " active" : ""}`}>{profile.is_active ? "Active" : "Inactive"}</span></div>
                  <div className="profile-inline-fields">
                    <label>Profile name<input required value={editProfileName} onChange={(event) => setEditProfileName(event.target.value)} /></label>
                    <label>Character name<input required value={editCharacterName} onChange={(event) => setEditCharacterName(event.target.value)} /></label>
                    <label>Voice profile<select value={editVoiceProfileId} onChange={(event) => setEditVoiceProfileId(event.target.value)} disabled={voicesQuery.isLoading || voicesQuery.isError}><option value="">Not assigned</option>{voicesQuery.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name} · {String(item.extra_settings.voice_name ?? item.provider_voice_id)}</option>)}</select>{!editVoiceProfileId && <small className="field-hint">This profile cannot generate speech or be used for a batch until a voice is attached.</small>}</label>
                    <label>Renderer<input className="profile-readonly-input" readOnly value={profile.renderer_provider} title="Renderer cannot be changed on an existing profile" /></label>
                    <label>Workflow template
                      <select value={editWorkflowTemplateId} onChange={(event) => setEditWorkflowTemplateId(event.target.value)} disabled={workflowsQuery.isLoading || workflowsQuery.isError}>
                        <option value="">No workflow — disconnect</option>
                        {profile.workflow_template_id && !workflow && <option value={profile.workflow_template_id}>Current workflow</option>}
                        {workflowsQuery.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}
                      </select>
                      {workflowsQuery.isError && <small className="field-hint">Workflows are unavailable. The current connection is preserved.</small>}
                    </label>
                  </div>
                  <div className="profile-edit-footer"><button className="button button-primary" type="submit" disabled={updateMutation.isPending || profileDependenciesUnavailable}>{updateMutation.isPending ? "Saving…" : "Save changes"}</button></div>
                  {updateMutation.isError && <p className="form-error" role="alert">{updateMutation.error.message}</p>}
                </form>
              </div>}
            </article>;
          })}
        </div>
      ) : (
        <div className="profile-empty compact-profile-empty"><div className="profile-stack"><span>◉</span><span>◒</span><span>✦</span></div><div><h3>No profiles yet</h3><p>Connect a character, voice, workflow, and renderer in one reusable configuration.</p></div></div>
      )}
      </div>

      <div id="profile-tab-create" className="profile-tab-panel" role="tabpanel" aria-labelledby="profile-tab-create-button" hidden={activeTab !== "create"}>
        <form className="profile-form profile-create-form" id="new-profile" onSubmit={submit}>
          <section className="profile-form-section">
            <div className="profile-form-section-heading"><h3>Profile</h3><p>Name the reusable configuration and choose its character.</p></div>
            <div className="profile-form-fields"><label>Profile name<input required value={profileName} onChange={(event) => setProfileName(event.target.value)} placeholder="Elena — Shelf — ComfyUI" /></label><label>Character<input required value={characterName} onChange={(event) => setCharacterName(event.target.value)} placeholder="Elena" /></label></div>
          </section>
          <section className="profile-form-section">
            <div className="profile-form-section-heading"><h3>Voice</h3><p>Attach a reusable voice profile used for generated speech.</p></div>
            <div className="profile-form-fields single"><label>Voice profile<select required value={voiceProfileId} onChange={(event) => setVoiceProfileId(event.target.value)} disabled={voicesQuery.isLoading || voicesQuery.isError}><option value="">Choose a voice profile…</option>{voicesQuery.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name} · {String(item.extra_settings.voice_name ?? item.provider_voice_id)}</option>)}</select>{voicesQuery.data?.items.length === 0 && <small className="field-hint">Create a voice profile before creating a render profile.</small>}</label><Link className="text-link profile-manage-link" href="/voice-profiles">Manage voice profiles →</Link></div>
          </section>
          <section className="profile-form-section">
            <div className="profile-form-section-heading"><h3>Rendering</h3><p>Select the ComfyUI workflow this profile will use.</p></div>
            <div className="profile-form-fields single"><label>Workflow template
              <select required value={workflowTemplateId} onChange={(event) => setWorkflowTemplateId(event.target.value)} disabled={workflowsQuery.isLoading || workflowsQuery.isError}>
                <option value="">Choose a saved workflow…</option>
                {workflowsQuery.data?.items.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name} · v{workflow.version}</option>)}
              </select>
              {workflowsQuery.isError ? <small className="field-hint">Workflows could not be loaded.</small> : workflowsQuery.data?.items.length === 0 ? <small className="field-hint">Import a workflow before creating a profile.</small> : null}
            </label></div>
          </section>
          <div className="profile-create-actions"><button className="button button-primary" type="submit" disabled={mutation.isPending || profileDependenciesUnavailable || !voiceProfileId || !workflowTemplateId}>{mutation.isPending ? "Saving…" : "Create profile"}</button></div>
          {mutation.isError && <p className="form-error" role="alert">{mutation.error.message}</p>}
        </form>
      </div>
      <ConfirmDialog open={pendingDelete !== null} title="Delete profile?" message={pendingDelete ? `“${pendingDelete.name}” will be permanently removed.` : ""} confirmLabel="Delete" onCancel={() => setPendingDelete(null)} onConfirm={() => { if (pendingDelete) deleteMutation.mutate(pendingDelete.id); setPendingDelete(null); }} />
      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
    </div>
  );
}
