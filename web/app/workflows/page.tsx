import Link from "next/link";
import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";
import { SavedWorkflowTemplates } from "@/components/workflow-template-setup";

export default function WorkflowsPage() {
  return (
    <main className="app-shell">
      <WorkspaceSidebar />
      <section className="content-area">
        <WorkspaceTopbar current="Workflows" />
        <div className="page-content"><section className="panel workflow-panel" aria-labelledby="workflows-title"><div className="panel-heading"><div><h1 id="workflows-title">Workflows</h1><p>Browse and edit your imported ComfyUI workflow templates.</p></div><Link className="button button-primary button-small" href="/#workflows">Import workflow</Link></div><SavedWorkflowTemplates /></section></div>
      </section>
    </main>
  );
}
