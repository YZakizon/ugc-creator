"use client";

import React, { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createWorkflowTemplate,
  deleteWorkflowTemplate,
  getWorkflowTemplates,
  getRenderProfiles,
  updateWorkflowTemplate,
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

const workflowValueTypes = ["string", "template", "integer", "number", "boolean"] as const;

export function WorkflowTemplateSetup({ initialTemplate, formId = "workflow-editor" }: { initialTemplate?: WorkflowTemplate; formId?: string } = {}) {
  const queryClient = useQueryClient();
  const formRef = useRef<HTMLFormElement>(null);
  const loadedTemplateIdRef = useRef<string | null>(null);
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

  const currentDefaultImage = selectedImage ?? mediaAssets.source_image;
  const currentDefaultAudio = selectedAudio ?? mediaAssets.audio;
  const mutation = useMutation<WorkflowTemplate, Error, { templateId: string | null; payload: WorkflowTemplateInput }>({
    mutationFn: ({ templateId, payload }) => templateId ? updateWorkflowTemplate(templateId, payload) : createWorkflowTemplate(payload),
    onSuccess: (template, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["workflow-templates"] });
      setEditingTemplateId(template.id);
      setToast({ message: variables.templateId ? "Workflow updated successfully." : "Workflow imported successfully.", variant: "success" });
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
    formRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [mutation]);

  useEffect(() => {
    if (initialTemplate && loadedTemplateIdRef.current !== initialTemplate.id) {
      loadedTemplateIdRef.current = initialTemplate.id;
      editTemplate(initialTemplate);
    }
  }, [editTemplate, initialTemplate]);

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
      validateLtxDimensions(workflowJson);
      validateBindingTargets(workflowJson, bindingJson);
      mutation.mutate({
        templateId: editingTemplateId,
        payload: {
        name: name.trim() || "ComfyUI workflow",
        metadata_json: { default_workflow_media: mediaAssets },
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
      <form ref={formRef} id={formId} className="workflow-form" onSubmit={submit}>
        {editingTemplateId && <p className="workflow-editing" role="status">Editing saved workflow.</p>}
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
          Default source image
          <input type="file" accept="image/*" disabled={mediaUploadPending} onChange={(event) => void selectMediaFile(event, "source_image")} />
          {currentDefaultImage ? <><small className="workflow-media-filename" title={currentDefaultImage}>Current file: <strong>{workflowMediaFilename(currentDefaultImage)}</strong></small><small className="field-hint">Content media overrides this default image.</small></> : <small className="field-hint">No default image saved. Used only when the content does not provide an image.</small>}
        </label>
        <label>
          Default audio
          <input type="file" accept="audio/*" disabled={mediaUploadPending} onChange={(event) => void selectMediaFile(event, "audio")} />
          {currentDefaultAudio ? <><small className="workflow-media-filename" title={currentDefaultAudio}>Current file: <strong>{workflowMediaFilename(currentDefaultAudio)}</strong></small><small className="field-hint">Content audio overrides this default audio.</small></> : <small className="field-hint">No default audio saved. Used only when the content does not provide audio.</small>}
        </label>
        <div className="workflow-json-editor">
          <WorkflowFieldTree workflow={workflow} workflowKind={workflowKind} onUpdateField={updatePromptInput} />
          <details className="workflow-json-source" open>
            <summary>ComfyUI API workflow JSON</summary>
            <textarea aria-label="ComfyUI API workflow JSON" value={workflow} onChange={(event) => updateWorkflowJson(event.target.value)} rows={10} spellCheck={false} placeholder="Paste or choose a ComfyUI API Format workflow JSON file." />
          </details>
        </div>
        <div className="workflow-actions">
          <button className="button button-primary" type="submit" disabled={mutation.isPending || mediaUploadPending}>{mutation.isPending ? "Updating…" : editingTemplateId ? "Update workflow" : "Import workflow"}</button>
          <button className="button button-secondary" type="button" onClick={resetWorkflow}>Reset workflow</button>
          <button className="button button-secondary" type="button" onClick={downloadWorkflow} disabled={!workflow.trim()}>Download updated JSON</button>
        </div>
        {(localError || mutation.isError) && <p className="form-error" role="alert">{localError ?? mutation.error?.message ?? "Workflow import failed."}</p>}
      </form>
      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
    </div>
  );
}

type WorkflowField = WorkflowInput & { value: string | number | boolean | null; rawValue: unknown; editable: boolean; label?: string };

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
          {isLtxWorkflow ? nodes.map((node) => {
            const field = node.inputs[0];
            if (!field) return null;
            const isSelected = selectedField !== undefined && workflowFieldKey(selectedField) === workflowFieldKey(field);
            return <div className="workflow-tree-field-container" key={workflowFieldKey(field)}>
              {isSelected && field.editable ? <div className="workflow-tree-field workflow-tree-field-editing workflow-ltx-control"><span>{field.label ?? field.inputName}</span><InlineWorkflowFieldEditor field={field} fieldTextareaRef={fieldTextareaRef} fieldSelectionRef={fieldSelectionRef} onUpdateField={onUpdateField} onInsertVariable={replaceSelectionWithVariable} /></div> : <button className={`workflow-tree-field workflow-ltx-control${isSelected ? " selected" : ""}`} type="button" disabled={!field.editable} onClick={() => setSelectedKey(workflowFieldKey(field))}><span>{field.label ?? field.inputName}</span><code>{formatWorkflowValue(field.value)}</code></button>}
            </div>;
          }) : nodes.map((node) => (
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
  const isDimension = isLtxDimensionField(field);

  return <div className={`workflow-inline-editor${isLargeText ? " large" : ""}`}>
    {stringValue !== null ? isLargeText ? <textarea ref={fieldTextareaRef} value={stringValue} rows={8} onChange={(event) => onUpdateField(field.nodeId, field.inputName, event.target.value)} onSelect={(event) => rememberFieldSelection(event.currentTarget, fieldSelectionRef)} onKeyUp={(event) => rememberFieldSelection(event.currentTarget, fieldSelectionRef)} onMouseUp={(event) => rememberFieldSelection(event.currentTarget, fieldSelectionRef)} onBlur={(event) => rememberFieldSelection(event.currentTarget, fieldSelectionRef)} /> : <input className="workflow-field-value" type="text" value={stringValue} onChange={(event) => onUpdateField(field.nodeId, field.inputName, event.target.value)} /> : <input className="workflow-field-value" type={typeof field.value === "number" ? "number" : "text"} min={isDimension ? 1 : undefined} step={isDimension ? 1 : undefined} value={String(field.value ?? "")} onChange={(event) => onUpdateField(field.nodeId, field.inputName, typeof field.value === "number" ? Number(event.target.value) : event.target.value)} />}
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
  const [expandedTemplateId, setExpandedTemplateId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; variant: ToastVariant } | null>(null);

  useEffect(() => {
    const templateId = window.location.hash.match(/^#workflow-(.+)$/)?.[1];
    const template = templatesQuery.data?.items.find((item) => item.id === templateId);
    if (!template) return;
    setExpandedTemplateId(template.logical_id);
    window.setTimeout(() => document.getElementById(`workflow-${template.id}`)?.scrollIntoView({ block: "center" }), 0);
  }, [templatesQuery.data]);

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
      {!templatesQuery.isLoading && !templatesQuery.isError && templatesQuery.data?.items.length === 0 && <p className="field-hint">No workflows yet. <Link className="text-link" href="/workflows#workflow-editor">Import workflow</Link>.</p>}
      {templatesQuery.data?.items.map((template) => {
        const isExpanded = expandedTemplateId === template.logical_id;
        return <article id={`workflow-${template.id}`} className={`saved-workflow saved-workflow-collapsible${isExpanded ? " expanded" : ""}`} key={template.logical_id}>
          <div className="saved-workflow-header">
            <button className="saved-workflow-toggle" type="button" aria-label={`${isExpanded ? "Hide" : "Show"} ${template.name} details`} aria-expanded={isExpanded} aria-controls={`workflow-details-${template.logical_id}`} onClick={() => setExpandedTemplateId(isExpanded ? null : template.logical_id)}>
              <span className="profile-list-icon">⌘</span>
              <span className="saved-workflow-summary"><strong>{template.name}</strong><small>{template.renderer_provider} · updated <HumanDate value={template.updated_at} /></small>{profilesQuery.isError ? <small className="workflow-used-by workflow-used-by-warning">Profile usage could not be checked.</small> : profilesUsing(template.id).length > 0 ? <small className="workflow-used-by">Used by: {profilesUsing(template.id).map((profile) => profile.name).join(", ")}</small> : null}</span>
              <svg className="profile-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5" /></svg>
            </button>
            <button className="icon-button workflow-icon-button danger" type="button" aria-label={`Delete ${template.name}`} title={profilesQuery.isLoading ? "Checking profile usage" : profilesQuery.isError ? "Profile usage unavailable" : profilesUsing(template.id).length > 0 ? "Disconnect connected profiles before deleting" : "Delete workflow"} disabled={deleteMutation.isPending || profilesQuery.isLoading || profilesQuery.isError || profilesUsing(template.id).length > 0} onClick={() => deleteTemplate(template)}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 14h8l1-14" /></svg>
            </button>
          </div>
          {isExpanded && <div id={`workflow-details-${template.logical_id}`} className="saved-workflow-details"><WorkflowTemplateSetup initialTemplate={template} formId={`workflow-editor-${template.logical_id}`} /></div>}
        </article>;
      })}
      <ConfirmDialog open={pendingDelete !== null} title="Delete workflow?" message={pendingDelete ? `“${pendingDelete.name}” will be permanently removed. Any render profile connected to it must be disconnected first; deletion will be blocked while it is in use.` : ""} confirmLabel="Delete" onCancel={() => setPendingDelete(null)} onConfirm={() => { if (pendingDelete) deleteMutation.mutate(pendingDelete.id); setPendingDelete(null); }} />
      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
    </div>
  );
}

export function WorkflowWorkspace() {
  const [activeTab, setActiveTab] = useState<"create" | "list">("list");
  return <div className="workflow-workspace">
    <div className="profile-tabs" role="tablist" aria-label="Workflow sections">
      <button id="workflow-tab-create-button" className={`profile-tab${activeTab === "create" ? " active" : ""}`} type="button" role="tab" aria-selected={activeTab === "create"} aria-controls="workflow-tab-create" onClick={() => setActiveTab("create")}>Create workflow</button>
      <button id="workflow-tab-list-button" className={`profile-tab${activeTab === "list" ? " active" : ""}`} type="button" role="tab" aria-selected={activeTab === "list"} aria-controls="workflow-tab-list" onClick={() => setActiveTab("list")}>Workflows</button>
    </div>
    <div id="workflow-tab-create" className="profile-tab-panel" role="tabpanel" aria-labelledby="workflow-tab-create-button" hidden={activeTab !== "create"}><WorkflowTemplateSetup formId="workflow-create-editor" /></div>
    <div id="workflow-tab-list" className="profile-tab-panel" role="tabpanel" aria-labelledby="workflow-tab-list-button" hidden={activeTab !== "list"}><SavedWorkflowTemplates /></div>
  </div>;
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
        rawValue,
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
      label: "Width",
      field: fields.find((field) => field.editable && typeof field.value === "number" && /^width$/i.test(field.title?.trim() ?? ""))
        ?? fields.find((field) => field.editable && typeof field.value === "number" && /^width$/i.test(field.inputName)),
    },
    {
      label: "Height",
      field: fields.find((field) => field.editable && typeof field.value === "number" && /^height$/i.test(field.title?.trim() ?? ""))
        ?? fields.find((field) => field.editable && typeof field.value === "number" && /^height$/i.test(field.inputName)),
    },
    {
      label: "Seed",
      field: primaryLtxSeedField(nodes),
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

function primaryLtxSeedField(nodes: WorkflowTreeNode[]): WorkflowField | undefined {
  const noiseSeeds = nodes.flatMap((node) => node.inputs)
    .filter((field) => field.editable && typeof field.value === "number" && /randomnoise/i.test(field.classType) && /noise.?seed/i.test(field.inputName));

  const basePassSeed = noiseSeeds.find((seed) => {
    const sampler = nodes.find((node) => /samplercustomadvanced/i.test(node.classType)
      && node.inputs.some((input) => input.inputName === "noise" && linkedNodeId(input.rawValue) === seed.nodeId));
    const sigmasNodeId = linkedNodeId(sampler?.inputs.find((input) => input.inputName === "sigmas")?.rawValue);
    const sigmas = nodes.find((node) => node.nodeId === sigmasNodeId)?.inputs.find((input) => input.inputName === "sigmas")?.rawValue;
    return typeof sigmas === "string" && /^\s*1(?:\.0+)?(?:\s*,|\s*$)/.test(sigmas);
  });

  return basePassSeed ?? noiseSeeds.at(-1);
}

function linkedNodeId(value: unknown): string | undefined {
  return Array.isArray(value) && typeof value[0] === "string" ? value[0] : undefined;
}

function workflowFieldKey(field: WorkflowField): string {
  return `${field.nodeId}::${field.inputName}`;
}

function isEditableWorkflowValue(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function isLtxDimensionField(field: WorkflowField): boolean {
  return field.label === "Width" || field.label === "Height";
}

function validateLtxDimensions(workflow: Record<string, unknown>) {
  if (detectWorkflowKind(workflow) !== "ltx-2.3") return;
  const dimensions: Array<{ label: "Width" | "Height"; value: unknown }> = [];

  for (const node of Object.values(workflow)) {
    if (!isRecord(node) || !isRecord(node.inputs)) continue;
    const title = nodeTitle(node)?.trim().toLowerCase();
    if (title === "width" || title === "height") {
      dimensions.push({ label: title === "width" ? "Width" : "Height", value: node.inputs.value });
    }
    for (const [inputName, value] of Object.entries(node.inputs)) {
      if ((/^width$/i.test(inputName) || /^height$/i.test(inputName)) && !Array.isArray(value)) {
        dimensions.push({ label: /^width$/i.test(inputName) ? "Width" : "Height", value });
      }
    }
  }

  for (const dimension of dimensions) {
    if (typeof dimension.value !== "number" || !Number.isInteger(dimension.value) || dimension.value <= 0) {
      throw new Error(`${dimension.label} must be a positive integer.`);
    }
  }
}

function formatWorkflowValue(value: string | number | boolean | null): string {
  if (value === null) return "linked/object value";
  const formatted = String(value).replace(/\s+/g, " ").trim();
  return formatted.length > 100 ? `${formatted.slice(0, 100)}…` : formatted;
}

function workflowMediaFromMetadata(metadata: Record<string, unknown>): Partial<Record<MediaKey, string>> {
  const rawMedia = metadata.default_workflow_media ?? metadata.workflow_media;
  if (!isRecord(rawMedia)) return {};
  return {
    source_image: typeof rawMedia.source_image === "string" ? rawMedia.source_image : undefined,
    audio: typeof rawMedia.audio === "string" ? rawMedia.audio : undefined,
  };
}

function workflowMediaFilename(assetKey: string): string {
  const storedName = assetKey.split("/").at(-1) ?? assetKey;
  return storedName.replace(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}-/i, "");
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
    if (!/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(binding.semantic_key)) throw new Error(`Invalid semantic parameter: ${binding.semantic_key}.`);
    if (seenKeys.has(binding.semantic_key)) throw new Error(`Only one ${binding.semantic_key} binding can be configured.`);
    seenKeys.add(binding.semantic_key);
    const node = workflow[binding.node_id];
    if (!isRecord(node) || !isRecord(node.inputs) || !(binding.input_name in node.inputs)) {
      throw new Error(`${semanticKeyLabel(binding.semantic_key)} points to missing input ${binding.node_id}.${binding.input_name}.`);
    }
  }
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
