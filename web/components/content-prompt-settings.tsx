"use client";

import React, { FormEvent, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Toast } from "@/components/feedback";
import { getContentPromptSettings, updateContentPromptSettings } from "@/lib/api";

export function ContentPromptSettings() {
  const client = useQueryClient();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const settings = useQuery({
    queryKey: ["content-prompt-settings"],
    queryFn: getContentPromptSettings,
  });
  const [prompt, setPrompt] = useState("");
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data) setPrompt(settings.data.prompt_template);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: updateContentPromptSettings,
    onSuccess: (saved) => {
      client.setQueryData(["content-prompt-settings"], saved);
      setPrompt(saved.prompt_template);
      setToast("OpenAI content prompt saved.");
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate(prompt.trim());
  }

  function insertPlaceholder(name: string) {
    const textarea = textareaRef.current;
    const variable = `{{${name}}}`;
    if (!textarea) {
      setPrompt((value) => value + variable);
      return;
    }
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    setPrompt((value) => value.slice(0, start) + variable + value.slice(end));
    requestAnimationFrame(() => {
      const cursor = start + variable.length;
      textarea.focus();
      textarea.setSelectionRange(cursor, cursor);
    });
  }

  function restoreDefault() {
    if (settings.data) save.mutate(settings.data.default_prompt_template);
  }

  return <div className="content-prompt-settings">
    <form className="profile-form content-prompt-form" onSubmit={submit}>
      <section className="profile-form-section">
        <div className="profile-form-section-heading">
          <h3>OpenAI content prompt</h3>
          <p>This instruction controls how OpenAI writes the speech script and social metadata. The topic is supplied separately for each job.</p>
        </div>
        <div className="content-prompt-editor">
          {settings.isLoading ? <p className="field-hint">Loading saved prompt…</p> : <>
            <label htmlFor="openai-content-prompt">Prompt template</label>
            <textarea
              id="openai-content-prompt"
              ref={textareaRef}
              required
              maxLength={20000}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
            />
            <div className="content-prompt-variables" aria-label="Prompt variables">
              <span>Insert variable</span>
              {settings.data?.supported_placeholders.map((name) => <button className="button button-secondary" key={name} type="button" onClick={() => insertPlaceholder(name)}>{`{{${name}}}`}</button>)}
            </div>
            <small className="field-hint">The duration variable is replaced for each job. Unknown variables are rejected when you save.</small>
            <div className="content-prompt-footer">
              <span>Version: {settings.data?.prompt_version ?? "—"}</span>
              <button className="button button-secondary" type="button" disabled={save.isPending || prompt === settings.data?.default_prompt_template} onClick={restoreDefault}>Restore default</button>
              <button className="button button-primary" disabled={save.isPending || !prompt.trim()}>{save.isPending ? "Saving…" : "Save prompt"}</button>
            </div>
          </>}
          {settings.isError && <p className="form-error">Prompt settings are unavailable: {settings.error.message}</p>}
          {save.isError && <p className="form-error">Could not save prompt: {save.error.message}</p>}
        </div>
      </section>
    </form>
    {toast && <Toast message={toast} variant="success" onClose={() => setToast(null)} />}
  </div>;
}
