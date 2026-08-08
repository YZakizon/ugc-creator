"use client";

import React, { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createWorkflowTemplate,
  createWorkflowTemplateVersion,
  deleteWorkflowTemplate,
  getWorkflowTemplates,
  getRenderProfiles,
  uploadWorkflowMedia,
} from "@/lib/api";
import type { WorkflowTemplate, WorkflowTemplateInput } from "@/lib/api";
import { ConfirmDialog, Toast, ToastVariant } from "@/components/feedback";
import { HumanDate } from "@/components/date-display";

const emptyWorkflow = "";
const emptyBindings = "[]";

type WorkflowInput = {
  nodeId: string;
  classType: string;
  inputName: string;
  title?: string;
};

type WorkflowKind = "unknown" | "comfyui" | "ltx-2.3";

const supportedTemplateVariables = [
  "SCRIPT",
  "TOPIC",
  "HOOK",
  "VIDEO_PROMPT",
  "DURATION",
  "CHARACTER_NAME",
] as const;

type MediaKey = "source_image" | "audio";
type WorkflowBinding = WorkflowTemplateInput["bindings"][number];

const semanticKeys = [
  "script",
  "video_prompt",
  "source_image",
  "audio",
  "seed",
  "fps",
  "duration",
  "frame_count",
  "width",
  "height",
] as const;

const workflowValueTypes = ["string", "template", "integer", "number", "boolean"] as const;

export function WorkflowTemplateSetup() {
  const queryClient = useQueryClient();
  const formRef = useRef<HTMLFormElement>(null);
  const [name, setName] = useState("");
  const [workflow, setWorkflow] = useState(emptyWorkflow);
  const [workflowKind, setWorkflowKind] = useState<WorkflowKind>("unknown");
  const [bindings, setBindings] = useState(emptyBindings);
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null);
  const [selectedImage, setSelectedImage] = useState<string | null>(null);
  const [selectedAudio, setSelectedAudio] = useState<string | null>(null);
  const [mediaAssets, setMediaAssets] = useState<Partial<Record<MediaKey, string>>>({});
  const [mediaUploadPending, setMediaUploadPending] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; variant: ToastVariant } | null>(null);
  const mutation = useMutation<WorkflowTemplate, Error, { templateId: string | null; payload: WorkflowTemplateInput }>({
    mutationFn: ({ templateId, payload }) => templateId ? createWorkflowTemplateVersion(templateId, payload) : createWorkflowTemplate(payload),
    onSuccess: (template) => {
      void queryClient.invalidateQueries({ queryKey: ["workflow-templates"] });
      setEditingTemplateId(null);
      setToast({ message: `Workflow version ${template.version} saved successfully.`, variant: "success" });
    },
  });

  function resetWorkflow() {
    formRef.current?.reset();
    setName("");
    setWorkflow(emptyWorkflow);
    setWorkflowKind("unknown");
    setBindings(emptyBindings);
    setEditingTemplateId(null);
    setSelectedImage(null);
    setSelectedAudio(null);
    setMediaAssets({});
    setLocalError(null);
    mutation.reset();
  }

  function downloadWorkflow() {
    const blob = new Blob([workflow], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${name.trim() || "comfyui-workflow"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function selectWorkflowFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const contents = typeof reader.result === "string" ? reader.result : "";
      try {
        const parsed = JSON.parse(contents) as Record<string, unknown>;
        const suggestedBindings = suggestBindings(parsed);
        setWorkflow(JSON.stringify(parsed, null, 2));
        setWorkflowKind(detectWorkflowKind(parsed));
        setBindings(JSON.stringify(suggestedBindings, null, 2));
        setSelectedImage(null);
        setSelectedAudio(null);
        setLocalError(null);
        mutation.reset();
      } catch {
        setLocalError("The selected file is not valid ComfyUI API workflow JSON.");
      }
    };
    reader.onerror = () => setLocalError("The workflow file could not be read.");
    reader.readAsText(file);
  }

  const editTemplate = useCallback((template: WorkflowTemplate) => {
    setEditingTemplateId(template.id);
    setName(template.name);
    setWorkflow(JSON.stringify(template.workflow_json, null, 2));
    setWorkflowKind(detectWorkflowKind(template.workflow_json));
    setBindings(JSON.stringify(template.bindings.map((binding) => ({
      semantic_key: binding.semantic_key,
      node_id: binding.node_id,
      input_name: binding.input_name,
      value_type: binding.value_type,
      required: binding.required,
    })), null, 2));
    setSelectedImage(null);
    setSelectedAudio(null);
    setMediaAssets(workflowMediaFromMetadata(template.metadata_json));
    setLocalError(null);
    mutation.reset();
    document.getElementById("workflow-editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [mutation]);

  useEffect(() => {
    const pendingTemplate = window.sessionStorage.getItem("workflow-template-edit");
    if (pendingTemplate) {
      try {
        editTemplate(JSON.parse(pendingTemplate) as WorkflowTemplate);
      } catch {
        setLocalError("The saved workflow could not be opened.");
      } finally {
        window.sessionStorage.removeItem("workflow-template-edit");
      }
    }
    function handleTemplateEdit(event: Event) {
      const template = (event as CustomEvent<WorkflowTemplate>).detail;
      if (template) editTemplate(template);
    }
    window.addEventListener("workflow-template-edit", handleTemplateEdit);
    return () => window.removeEventListener("workflow-template-edit", handleTemplateEdit);
  }, [editTemplate]);

  function updateWorkflowJson(value: string) {
    setWorkflow(value);
    try {
      const parsed = JSON.parse(value) as Record<string, unknown>;
      setWorkflowKind(detectWorkflowKind(parsed));
      setLocalError(null);
    } catch { /* Keep the raw text editable until it becomes valid JSON again. */ }
  }

  function updatePromptInput(nodeId: string, inputName: string, value: string | number | boolean | null) {
    try {
      const parsed = JSON.parse(workflow) as Record<string, unknown>;
      const node = parsed[nodeId];
      if (!isRecord(node) || !isRecord(node.inputs)) {
        throw new Error("The prompt input references a missing workflow node.");
      }
      node.inputs[inputName] = value;
      setWorkflow(JSON.stringify(parsed, null, 2));
      setLocalError(null);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "The prompt input could not be updated.");
    }
  }

  async function selectMediaFile(
    event: React.ChangeEvent<HTMLInputElement>,
    semanticKey: "source_image" | "audio",
  ) {
    const file = event.target.files?.[0];
    if (!file) return;
    setMediaUploadPending(true);
    try {
      const parsedWorkflow = JSON.parse(workflow) as Record<string, unknown>;
      let parsedBindings = parseBindings(bindings);
      let binding = parsedBindings.find((item) => item.semantic_key === semanticKey);
      if (!binding) {
        binding = suggestBindings(parsedWorkflow).find((item) => item.semantic_key === semanticKey);
        if (binding) {
          parsedBindings = [...parsedBindings, binding];
          setBindings(JSON.stringify(parsedBindings, null, 2));
        }
      }
      if (!binding || typeof binding.node_id !== "string" || typeof binding.input_name !== "string") {
        throw new Error(`No ${semanticKey} input was detected in this workflow.`);
      }
      const node = parsedWorkflow[binding.node_id];
      if (!isRecord(node) || !isRecord(node.inputs)) {
        throw new Error(`Binding ${semanticKey} references a missing workflow node.`);
      }
      const dataUrl = await readFileAsDataUrl(file);
      const base64 = dataUrl.split(",", 2)[1];
      if (!base64) throw new Error("The media file could not be encoded.");
      const uploaded = await uploadWorkflowMedia({
        filename: file.name,
        content_base64: base64,
        input_type: semanticKey === "source_image" ? "image" : "audio",
      });
      const placeholder = semanticKey === "source_image" ? "{{SOURCE_IMAGE}}" : "{{AUDIO}}";
      node.inputs[binding.input_name] = placeholder;
      setWorkflow(JSON.stringify(parsedWorkflow, null, 2));
      setMediaAssets((current) => ({ ...current, [semanticKey]: uploaded.asset_key }));
      if (semanticKey === "source_image") setSelectedImage(uploaded.asset_key);
      else setSelectedAudio(uploaded.asset_key);
      setLocalError(null);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "The media file could not be uploaded.");
    } finally {
      setMediaUploadPending(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);
    try {
      const workflowJson = JSON.parse(workflow) as Record<string, unknown>;
      const bindingJson = parseBindings(bindings);
      validateBindingTargets(workflowJson, bindingJson);
      mutation.mutate({
        templateId: editingTemplateId,
        payload: {
        name: name.trim() || "ComfyUI workflow",
        metadata_json: { workflow_media: mediaAssets },
        workflow_json: workflowJson,
        bindings: bindingJson,
        },
      });
    } catch (error) {
      mutation.reset();
      setLocalError(error instanceof Error ? error.message : "Workflow and bindings must be valid JSON.");
    }
  }

  return (
    <div className="workflow-setup">
      <form ref={formRef} id="workflow-editor" className="workflow-form" onSubmit={submit}>
        {editingTemplateId && <p className="workflow-editing" role="status">Editing a saved workflow. Saving creates a new template version.</p>}
        <label>
          Template name
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Shelf — LTX 2.3" />
        </label>
        <label>
          Import API workflow file
          <input type="file" accept="application/json,.json" onChange={selectWorkflowFile} />
          <small className="field-hint">Choose the JSON exported with Save (API Format).</small>
        </label>
        <label>
          Source image
          <input type="file" accept="image/*" disabled={mediaUploadPending} onChange={(event) => void selectMediaFile(event, "source_image")} />
          <small className="field-hint">{selectedImage ? `Saved asset: ${selectedImage}` : "Requires a source_image binding."}</small>
        </label>
        <label>
          Audio
          <input type="file" accept="audio/*" disabled={mediaUploadPending} onChange={(event) => void selectMediaFile(event, "audio")} />
          <small className="field-hint">{selectedAudio ? `Saved asset: ${selectedAudio}` : "Requires an audio binding."}</small>
        </label>
        <div className="workflow-json-editor">
          <label>
            ComfyUI API workflow JSON
            <textarea value={workflow} onChange={(event) => updateWorkflowJson(event.target.value)} rows={10} spellCheck={false} placeholder="Paste or choose a ComfyUI API Format workflow JSON file." />
          </label>
          <WorkflowFieldTree workflow={workflow} workflowKind={workflowKind} onUpdateField={updatePromptInput} />
          <SemanticBindingEditor workflow={workflow} bindings={bindings} onChange={setBindings} />
        </div>
        <div className="workflow-actions">
          <button className="button button-primary" type="submit" disabled={mutation.isPending || mediaUploadPending}>{mutation.isPending ? "Saving…" : editingTemplateId ? "Save updated workflow" : "Import workflow"}</button>
          <button className="button button-secondary" type="button" onClick={resetWorkflow}>Reset workflow</button>
          <button className="button button-secondary" type="button" onClick={downloadWorkflow} disabled={!workflow.trim()}>Download updated JSON</button>
        </div>
        {(localError || mutation.isError) && <p className="form-error" role="alert">{localError ?? mutation.error?.message ?? "Workflow import failed."}</p>}
      </form>
      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
    </div>
  );
}

type SemanticBindingEditorProps = {
  workflow: string;
  bindings: string;
  onChange: (value: string) => void;
};

function SemanticBindingEditor({ workflow, bindings, onChange }: SemanticBindingEditorProps) {
  const inputs = parseWorkflowInputs(workflow);
  let parsedBindings: WorkflowBinding[] = [];
  let bindingError: string | null = null;
  try {
    parsedBindings = parseBindings(bindings);
  } catch (error) {
    bindingError = error instanceof Error ? error.message : "Bindings could not be read.";
  }
  const usedKeys = new Set(parsedBindings.map((binding) => binding.semantic_key));

  function commit(next: WorkflowBinding[]) {
    onChange(JSON.stringify(next, null, 2));
  }

  function updateBinding(index: number, patch: Partial<WorkflowBinding>) {
    commit(parsedBindings.map((binding, bindingIndex) => bindingIndex === index ? { ...binding, ...patch } : binding));
  }

  function selectTarget(index: number, value: string) {
    const separator = value.indexOf("::");
    if (separator < 0) return;
    updateBinding(index, { node_id: value.slice(0, separator), input_name: value.slice(separator + 2) });
  }

  function addBinding() {
    const semanticKey = semanticKeys.find((key) => !usedKeys.has(key));
    const input = inputs[0];
    if (!semanticKey || !input) return;
    commit([...parsedBindings, {
      semantic_key: semanticKey,
      node_id: input.nodeId,
      input_name: input.inputName,
      value_type: defaultValueType(semanticKey),
      required: true,
    }]);
  }

  return (
    <section className="semantic-binding-editor" aria-labelledby="semantic-bindings-title">
      <div className="semantic-binding-heading">
        <div><strong id="semantic-bindings-title">Semantic bindings</strong><small>Map job values to any input in this workflow. Bindings are preserved when you edit the workflow JSON.</small></div>
        <button className="button button-secondary button-small" type="button" disabled={Boolean(bindingError) || inputs.length === 0 || usedKeys.size >= semanticKeys.length} onClick={addBinding}>＋ Add binding</button>
      </div>
      {bindingError ? <p className="form-error" role="alert">{bindingError}</p> : parsedBindings.length === 0 ? <p className="field-hint">No bindings configured. Add one to connect batch values such as script, seed, FPS, or duration.</p> : (
        <div className="semantic-binding-list">
          {parsedBindings.map((binding, index) => {
            const targetValue = `${binding.node_id}::${binding.input_name}`;
            const targetExists = inputs.some((input) => `${input.nodeId}::${input.inputName}` === targetValue);
            return <div className={`semantic-binding-row${targetExists ? "" : " invalid"}`} key={`${binding.semantic_key}-${index}`}>
              <label>Parameter
                <select aria-label={`Binding ${index + 1} parameter`} value={binding.semantic_key} onChange={(event) => updateBinding(index, { semantic_key: event.target.value })}>
                  {semanticKeys.map((key) => <option key={key} value={key} disabled={key !== binding.semantic_key && usedKeys.has(key)}>{semanticKeyLabel(key)}</option>)}
                </select>
              </label>
              <label>Workflow node input
                <select aria-label={`Binding ${index + 1} workflow node input`} value={targetValue} onChange={(event) => selectTarget(index, event.target.value)}>
                  {!targetExists && <option value={targetValue}>Missing: {binding.node_id}.{binding.input_name}</option>}
                  {inputs.map((input) => <option key={`${input.nodeId}::${input.inputName}`} value={`${input.nodeId}::${input.inputName}`}>{input.title ? `${input.title} · ` : ""}{input.nodeId}.{input.inputName} ({input.classType})</option>)}
                </select>
              </label>
              <label>Value type
                <select aria-label={`Binding ${index + 1} value type`} value={binding.value_type} onChange={(event) => updateBinding(index, { value_type: event.target.value as WorkflowBinding["value_type"] })}>
                  {workflowValueTypes.map((valueType) => <option key={valueType} value={valueType}>{valueType}</option>)}
                </select>
              </label>
              <label className="semantic-binding-required"><input type="checkbox" checked={binding.required} onChange={(event) => updateBinding(index, { required: event.target.checked })} /> Required</label>
              <button className="icon-button workflow-icon-button danger" type="button" aria-label={`Remove ${binding.semantic_key} binding`} title="Remove binding" onClick={() => commit(parsedBindings.filter((_, bindingIndex) => bindingIndex !== index))}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg>
              </button>
              {!targetExists && <small className="semantic-binding-error">This binding points to an input that is not present in the current workflow JSON.</small>}
            </div>;
          })}
        </div>
      )}
    </section>
  );
}

type WorkflowField = WorkflowInput & { value: string | number | boolean | null; editable: boolean; label?: string };

type WorkflowFieldTreeProps = {
  workflow: string;
  workflowKind: WorkflowKind;
  onUpdateField: (nodeId: string, inputName: string, value: string | number | boolean | null) => void;
};

function WorkflowFieldTree({ workflow, workflowKind, onUpdateField }: WorkflowFieldTreeProps) {
  const [selectedKey, setSelectedKey] = useState("");
  const fieldTextareaRef = useRef<HTMLTextAreaElement>(null);
  const fieldSelectionRef = useRef({ start: 0, end: 0 });
  const allNodes = parseWorkflowNodes(workflow);
  const isLtxWorkflow = workflowKind === "ltx-2.3";
  const nodes = isLtxWorkflow ? ltxWorkflowNodes(allNodes) : allNodes;
  const fields = nodes.flatMap((node) => node.inputs);
  const selectedField = fields.find((field) => workflowFieldKey(field) === selectedKey);

  useEffect(() => {
    if (selectedKey && !selectedField) setSelectedKey("");
  }, [selectedField, selectedKey, fields]);

  function replaceSelectionWithVariable(variable: string) {
    if (!selectedField || typeof selectedField.value !== "string") return;
    const token = `{{${variable}}}`;
    const selectionStart = Math.min(fieldSelectionRef.current.start, selectedField.value.length);
    const selectionEnd = Math.min(Math.max(fieldSelectionRef.current.end, selectionStart), selectedField.value.length);
    const cursorPosition = selectionStart + token.length;
    onUpdateField(selectedField.nodeId, selectedField.inputName, `${selectedField.value.slice(0, selectionStart)}${token}${selectedField.value.slice(selectionEnd)}`);
    window.requestAnimationFrame(() => {
      fieldTextareaRef.current?.focus();
      fieldTextareaRef.current?.setSelectionRange(cursorPosition, cursorPosition);
    });
  }

  return (
    <div className="workflow-tree-editor">
      <div className="workflow-prompts-heading">
        <strong>{isLtxWorkflow ? "LTX 2.3 controls" : "Workflow fields"}</strong>
        <span className="workflow-kind-badge">{workflowKind === "ltx-2.3" ? "Detected: LTX 2.3" : workflowKind === "comfyui" ? "Detected: ComfyUI workflow" : "Workflow type not detected"}</span>
        <small>{isLtxWorkflow ? "Expand a control and edit the value. These controls update the JSON above; other node inputs remain available in the raw JSON." : "Expand a node and click an input to edit its value. Changes update the workflow JSON and are saved with the workflow."}</small>
      </div>
      {nodes.length === 0 ? <p className="field-hint">No workflow nodes available. Load valid ComfyUI API JSON above.</p> : (
        <div className="workflow-tree">
          {nodes.map((node) => (
            <details className="workflow-tree-node" key={node.nodeId}>
              <summary><span>{node.title ? `${node.title} · ` : ""}{node.nodeId}</span><small>{node.classType}</small></summary>
              <div className="workflow-tree-fields">
                {node.inputs.map((field) => {
                  const isSelected = selectedField !== undefined && workflowFieldKey(selectedField) === workflowFieldKey(field);
                  return <div className="workflow-tree-field-container" key={workflowFieldKey(field)}>
                    {isSelected && field.editable ? <div className="workflow-tree-field workflow-tree-field-editing"><span>{field.label ?? field.inputName}</span><InlineWorkflowFieldEditor field={field} fieldTextareaRef={fieldTextareaRef} fieldSelectionRef={fieldSelectionRef} onUpdateField={onUpdateField} onInsertVariable={replaceSelectionWithVariable} /></div> : <button className={`workflow-tree-field${isSelected ? " selected" : ""}`} type="button" disabled={!field.editable} onClick={() => setSelectedKey(workflowFieldKey(field))}><span>{field.label ?? field.inputName}</span><code>{formatWorkflowValue(field.value)}</code></button>}
                  </div>;
                })}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

type InlineWorkflowFieldEditorProps = {
  field: WorkflowField;
  fieldTextareaRef: React.MutableRefObject<HTMLTextAreaElement | null>;
  fieldSelectionRef: React.MutableRefObject<{ start: number; end: number }>;
  onUpdateField: WorkflowFieldTreeProps["onUpdateField"];
  onInsertVariable: (variable: string) => void;
};

function InlineWorkflowFieldEditor({ field, fieldTextareaRef, fieldSelectionRef, onUpdateField, onInsertVariable }: InlineWorkflowFieldEditorProps) {
  const stringValue = typeof field.value === "string" ? field.value : null;
  const isLargeText = stringValue !== null && (stringValue.includes("\n") || stringValue.length > 120 || isPromptInput(field.classType, field.inputName, field.title));

  return <div className={`workflow-inline-editor${isLargeText ? " large" : ""}`}>
    {stringValue !== null ? isLargeText ? <textarea ref={fieldTextareaRef} value={stringValue} rows={8} onChange={(event) => onUpdateField(field.nodeId, field.inputName, event.target.value)} onSelect={(event) => rememberFieldSelection(event.currentTarget, fieldSelectionRef)} onKeyUp={(event) => rememberFieldSelection(event.currentTarget, fieldSelectionRef)} onMouseUp={(event) => rememberFieldSelection(event.currentTarget, fieldSelectionRef)} onBlur={(event) => rememberFieldSelection(event.currentTarget, fieldSelectionRef)} /> : <input className="workflow-field-value" type="text" value={stringValue} onChange={(event) => onUpdateField(field.nodeId, field.inputName, event.target.value)} /> : <input className="workflow-field-value" type={typeof field.value === "number" ? "number" : "text"} value={String(field.value ?? "")} onChange={(event) => onUpdateField(field.nodeId, field.inputName, typeof field.value === "number" ? Number(event.target.value) : event.target.value)} />}
    {isLargeText && isPromptInput(field.classType, field.inputName, field.title) && <span className="prompt-template-vars"><small>Select text, then replace it with:</small>{supportedTemplateVariables.map((variable) => <button className="prompt-var" type="button" key={variable} onClick={() => onInsertVariable(variable)}>+ {`{{${variable}}}`}</button>)}</span>}
  </div>;
}

function rememberFieldSelection(textarea: HTMLTextAreaElement, selectionRef: React.MutableRefObject<{ start: number; end: number }>) {
  selectionRef.current = { start: textarea.selectionStart, end: textarea.selectionEnd };
}

export function SavedWorkflowTemplates() {
  const queryClient = useQueryClient();
  const templatesQuery = useQuery({
    queryKey: ["workflow-templates"],
    queryFn: getWorkflowTemplates,
  });
  const profilesQuery = useQuery({
    queryKey: ["render-profiles"],
    queryFn: getRenderProfiles,
  });
  const deleteMutation = useMutation({
    mutationFn: deleteWorkflowTemplate,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["workflow-templates"] });
      setToast({ message: "Workflow deleted.", variant: "success" });
    },
    onError: (error) => setToast({ message: error.message, variant: "danger" }),
  });
  const [pendingDelete, setPendingDelete] = useState<WorkflowTemplate | null>(null);
  const [toast, setToast] = useState<{ message: string; variant: ToastVariant } | null>(null);

  function editTemplate(template: WorkflowTemplate) {
    window.sessionStorage.setItem("workflow-template-edit", JSON.stringify(template));
    window.location.assign("/#workflows");
  }

  function deleteTemplate(template: WorkflowTemplate) {
    setPendingDelete(template);
  }

  function profilesUsing(templateId: string) {
    return profilesQuery.data?.items.filter((profile) => profile.workflow_template_id === templateId) ?? [];
  }

  return (
    <div className="saved-workflows" aria-label="Saved workflow templates">
      <div className="saved-workflows-heading"><strong>Workflows</strong><small>{templatesQuery.data?.total ?? 0} template{templatesQuery.data?.total === 1 ? "" : "s"}</small></div>
      {templatesQuery.isLoading && <p className="field-hint">Loading saved workflows…</p>}
      {templatesQuery.isError && <p className="form-error" role="alert">Saved workflows are unavailable: {templatesQuery.error.message}</p>}
      {!templatesQuery.isLoading && !templatesQuery.isError && templatesQuery.data?.items.length === 0 && <p className="field-hint">No workflows yet. <Link className="text-link" href="/#workflows">Import workflow</Link>.</p>}
      {templatesQuery.data?.items.map((template) => (
        <article className="saved-workflow" key={template.id}>
          <div>
            <strong>{template.name}</strong>
            <small>{template.renderer_provider} · v{template.version} · {template.bindings.length} binding{template.bindings.length === 1 ? "" : "s"} · created <HumanDate value={template.created_at} /></small>
            {profilesQuery.isError ? <small className="workflow-used-by workflow-used-by-warning">Profile usage could not be checked.</small> : profilesUsing(template.id).length > 0 ? <small className="workflow-used-by">Used by: {profilesUsing(template.id).map((profile) => profile.name).join(", ")}. Disconnect these profiles before deleting.</small> : null}
          </div>
          <div className="saved-workflow-actions">
            <button className="icon-button workflow-icon-button" type="button" aria-label={`Edit ${template.name}`} title="Edit workflow" onClick={() => editTemplate(template)}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 16.5-.8 3.3 3.3-.8L18.2 7.3a2.1 2.1 0 0 0 0-3l-.5-.5a2.1 2.1 0 0 0-3 0L4 16.5Zm9.5-10.8 5.3 5.3M4 21h16" /></svg>
            </button>
            <button className="icon-button workflow-icon-button danger" type="button" aria-label={`Delete ${template.name}`} title={profilesQuery.isLoading ? "Checking profile usage" : profilesQuery.isError ? "Profile usage unavailable" : profilesUsing(template.id).length > 0 ? "Disconnect connected profiles before deleting" : "Delete workflow"} disabled={deleteMutation.isPending || profilesQuery.isLoading || profilesQuery.isError || profilesUsing(template.id).length > 0} onClick={() => deleteTemplate(template)}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg>
            </button>
          </div>
        </article>
      ))}
      <ConfirmDialog open={pendingDelete !== null} title="Delete workflow?" message={pendingDelete ? `“${pendingDelete.name}” will be permanently removed. Any render profile connected to it must be disconnected first; deletion will be blocked while it is in use.` : ""} confirmLabel="Delete" onCancel={() => setPendingDelete(null)} onConfirm={() => { if (pendingDelete) deleteMutation.mutate(pendingDelete.id); setPendingDelete(null); }} />
      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
    </div>
  );
}

function extractInputs(workflow: Record<string, unknown>): WorkflowInput[] {
  return Object.entries(workflow).flatMap(([nodeId, rawNode]) => {
    if (!isRecord(rawNode) || typeof rawNode.class_type !== "string" || !isRecord(rawNode.inputs)) return [];
    const title = nodeTitle(rawNode);
    return Object.keys(rawNode.inputs).map((inputName) => ({ nodeId, classType: rawNode.class_type as string, inputName, title }));
  });
}

function detectWorkflowKind(workflow: Record<string, unknown>): WorkflowKind {
  const nodes = Object.values(workflow).filter(isRecord);
  if (nodes.some((node) => {
    const classType = typeof node.class_type === "string" ? node.class_type : "";
    const title = nodeTitle(node) ?? "";
    return /ltx/i.test(classType) || /ltx/i.test(title);
  })) return "ltx-2.3";
  return nodes.some((node) => typeof node.class_type === "string" && isRecord(node.inputs)) ? "comfyui" : "unknown";
}

type WorkflowTreeNode = {
  nodeId: string;
  classType: string;
  title?: string;
  inputs: WorkflowField[];
};

function parseWorkflowNodes(value: string): WorkflowTreeNode[] {
  try {
    const workflow = JSON.parse(value) as Record<string, unknown>;
    return Object.entries(workflow).flatMap(([nodeId, rawNode]) => {
      if (!isRecord(rawNode) || typeof rawNode.class_type !== "string" || !isRecord(rawNode.inputs)) return [];
      const title = nodeTitle(rawNode);
      const inputs = Object.entries(rawNode.inputs).map(([inputName, rawValue]) => ({
        nodeId,
        classType: rawNode.class_type as string,
        inputName,
        title,
        editable: isEditableWorkflowValue(rawValue),
        value: isEditableWorkflowValue(rawValue) ? rawValue : null,
      }));
      return [{ nodeId, classType: rawNode.class_type, title, inputs }];
    });
  } catch {
    return [];
  }
}

function ltxWorkflowNodes(nodes: WorkflowTreeNode[]): WorkflowTreeNode[] {
  const fields = nodes.flatMap((node) => node.inputs);
  const controls: Array<{ label: string; field: WorkflowField | undefined }> = [
    {
      label: "Image source",
      field: fields.find((field) => field.editable && field.inputName === "image" && /loadimage/i.test(field.classType)),
    },
    {
      label: "Audio source",
      field: fields.find((field) => field.editable && field.inputName === "audio" && /loadaudio/i.test(field.classType)),
    },
    {
      label: "Prompts",
      field: fields.find((field) => field.editable && typeof field.value === "string" && field.title?.trim().toLowerCase() === "prompt")
        ?? fields.find((field) => field.editable && typeof field.value === "string" && /primitivestringmultiline/i.test(field.classType))
        ?? fields.find((field) => field.editable && typeof field.value === "string" && /prompt/i.test(field.title ?? ""))
        ?? fields.find((field) => field.editable && typeof field.value === "string" && isPromptInput(field.classType, field.inputName, field.title)),
    },
    {
      label: "FPS",
      field: fields.find((field) => field.editable && typeof field.value === "number" && (/frame.?rate/i.test(field.title ?? "") || /^fps$/i.test(field.inputName) || /frame.?rate/i.test(field.inputName))),
    },
    {
      label: "Duration",
      field: fields.find((field) => field.editable && typeof field.value === "number" && (/duration/i.test(field.title ?? "") || /^duration$/i.test(field.inputName))),
    },
    {
      label: "Seed",
      field: fields.find((field) => field.editable && typeof field.value === "number" && (/^seed$/i.test(field.inputName) || /\.seed$/i.test(field.inputName)))
        ?? fields.find((field) => field.editable && typeof field.value === "number" && /noise.?seed/i.test(field.inputName)),
    },
  ];

  return controls.flatMap(({ label, field }) => {
    if (!field) return [];
    return [{
      nodeId: field.nodeId,
      classType: field.classType,
      title: label,
      inputs: [{ ...field, label }],
    }];
  });
}

function workflowFieldKey(field: WorkflowField): string {
  return `${field.nodeId}::${field.inputName}`;
}

function isEditableWorkflowValue(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function formatWorkflowValue(value: string | number | boolean | null): string {
  if (value === null) return "linked/object value";
  const formatted = String(value).replace(/\s+/g, " ").trim();
  return formatted.length > 100 ? `${formatted.slice(0, 100)}…` : formatted;
}

function workflowMediaFromMetadata(metadata: Record<string, unknown>): Partial<Record<MediaKey, string>> {
  const rawMedia = metadata.workflow_media;
  if (!isRecord(rawMedia)) return {};
  return {
    source_image: typeof rawMedia.source_image === "string" ? rawMedia.source_image : undefined,
    audio: typeof rawMedia.audio === "string" ? rawMedia.audio : undefined,
  };
}

function isPromptInput(classType: string, inputName: string, title?: string): boolean {
  return /prompt|text|value|positive|negative|caption|script/i.test(inputName)
    || /prompt|positive|negative|caption|script/i.test(title ?? "")
    || /primitive.*string|textencode|prompt/i.test(classType);
}

function nodeTitle(node: Record<string, unknown>): string | undefined {
  return isRecord(node._meta) && typeof node._meta.title === "string" ? node._meta.title : undefined;
}

function suggestBindings(workflow: Record<string, unknown>): WorkflowBinding[] {
  const inputs = extractInputs(workflow);
  const image = inputs.find((input) => input.inputName === "image" && /loadimage/i.test(input.classType));
  const audio = inputs.find((input) => input.inputName === "audio" && /loadaudio/i.test(input.classType));
  const script = inputs.find((input) => /primitivestringmultiline/i.test(input.classType)) ?? inputs.find((input) => ["text", "prompt", "value"].includes(input.inputName));
  return ([
    ["script", script, "template"],
    ["source_image", image, "string"],
    ["audio", audio, "string"],
  ] as const).flatMap(([semanticKey, input, valueType]) => input ? [{ semantic_key: semanticKey, node_id: input.nodeId, input_name: input.inputName, value_type: valueType, required: true }] : []);
}

function parseWorkflowInputs(value: string): WorkflowInput[] {
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    return extractInputs(parsed);
  } catch {
    return [];
  }
}

function parseBindings(value: string): WorkflowBinding[] {
  const parsed = JSON.parse(value) as unknown;
  if (!Array.isArray(parsed)) throw new Error("Semantic bindings must be a JSON array.");
  return parsed.map((rawBinding, index) => {
    if (!isRecord(rawBinding)
      || typeof rawBinding.semantic_key !== "string"
      || typeof rawBinding.node_id !== "string"
      || typeof rawBinding.input_name !== "string"
      || typeof rawBinding.value_type !== "string"
      || !workflowValueTypes.includes(rawBinding.value_type as WorkflowBinding["value_type"])
      || typeof rawBinding.required !== "boolean") {
      throw new Error(`Semantic binding ${index + 1} is incomplete or invalid.`);
    }
    return {
      semantic_key: rawBinding.semantic_key,
      node_id: rawBinding.node_id,
      input_name: rawBinding.input_name,
      value_type: rawBinding.value_type as WorkflowBinding["value_type"],
      required: rawBinding.required,
    };
  });
}

function validateBindingTargets(workflow: Record<string, unknown>, bindings: WorkflowBinding[]) {
  const seenKeys = new Set<string>();
  for (const binding of bindings) {
    if (!semanticKeys.includes(binding.semantic_key as (typeof semanticKeys)[number])) {
      throw new Error(`Unsupported semantic parameter: ${binding.semantic_key}.`);
    }
    if (seenKeys.has(binding.semantic_key)) throw new Error(`Only one ${binding.semantic_key} binding can be configured.`);
    seenKeys.add(binding.semantic_key);
    const node = workflow[binding.node_id];
    if (!isRecord(node) || !isRecord(node.inputs) || !(binding.input_name in node.inputs)) {
      throw new Error(`${semanticKeyLabel(binding.semantic_key)} points to missing input ${binding.node_id}.${binding.input_name}.`);
    }
  }
}

function defaultValueType(semanticKey: string): WorkflowBinding["value_type"] {
  if (["seed", "fps", "frame_count", "width", "height"].includes(semanticKey)) return "integer";
  if (semanticKey === "duration") return "number";
  if (["script", "video_prompt"].includes(semanticKey)) return "template";
  return "string";
}

function semanticKeyLabel(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(new Error("The media file could not be read."));
    reader.readAsDataURL(file);
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
