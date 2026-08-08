"use client";

import React, { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog, Toast } from "@/components/feedback";
import { checkRenderNode, createRenderNode, deleteRenderNode, getRenderNodes, type RenderNode } from "@/lib/api";

export function RenderNodeSettings() {
  const client = useQueryClient();
  const nodes = useQuery({ queryKey: ["render-nodes"], queryFn: getRenderNodes, refetchInterval: 10000 });
  const [name, setName] = useState("Local ComfyUI");
  const [baseUrl, setBaseUrl] = useState("http://host.docker.internal:8188");
  const [pendingDelete, setPendingDelete] = useState<RenderNode | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const refresh = () => void client.invalidateQueries({ queryKey: ["render-nodes"] });
  const create = useMutation({ mutationFn: createRenderNode, onSuccess: () => { refresh(); setToast("Render node saved."); } });
  const health = useMutation({ mutationFn: checkRenderNode, onSuccess: (node) => { refresh(); setToast(node.health_status === "healthy" ? "ComfyUI is connected." : node.health_message ?? "ComfyUI is unavailable."); } });
  const remove = useMutation({ mutationFn: deleteRenderNode, onSuccess: () => { refresh(); setToast("Render node deleted."); } });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    create.mutate({ name: name.trim(), base_url: baseUrl.trim(), is_active: true });
  }

  return <div className="render-node-settings">
    <form className="profile-form render-node-form" onSubmit={submit}>
      <section className="profile-form-section"><div className="profile-form-section-heading"><h3>ComfyUI render node</h3><p>Use a URL reachable from the API and worker containers.</p></div><div className="profile-form-fields"><label>Node name<input required value={name} onChange={(event) => setName(event.target.value)} /></label><label>ComfyUI URL<input required type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} /></label></div></section>
      <div className="profile-create-actions"><button className="button button-primary" disabled={create.isPending}>{create.isPending ? "Saving…" : "Add render node"}</button></div>
      {create.isError && <p className="form-error">{create.error.message}</p>}
    </form>
    <div className="render-node-list">{nodes.data?.items.map((node) => <article className="render-node-card" key={node.id}><div><strong>{node.name}</strong><small>{node.base_url}</small></div><span className={`node-health ${node.health_status}`}>{node.health_status}</span><button className="button button-secondary" type="button" disabled={health.isPending} onClick={() => health.mutate(node.id)}>Test connection</button><button className="icon-button danger" aria-label={`Delete ${node.name}`} onClick={() => setPendingDelete(node)}>⌫</button>{node.health_message && <p>{node.health_message}</p>}</article>)}</div>
    {nodes.isError && <p className="form-error">Render nodes are unavailable: {nodes.error.message}</p>}
    <ConfirmDialog open={pendingDelete !== null} title="Delete render node?" message={pendingDelete ? `Delete “${pendingDelete.name}”? Nodes with render history cannot be deleted.` : ""} confirmLabel="Delete" onCancel={() => setPendingDelete(null)} onConfirm={() => { if (pendingDelete) remove.mutate(pendingDelete.id); setPendingDelete(null); }} />
    {toast && <Toast message={toast} variant="success" onClose={() => setToast(null)} />}
  </div>;
}
