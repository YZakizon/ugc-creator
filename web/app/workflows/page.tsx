import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";
import { WorkflowWorkspace } from "@/components/workflow-template-setup";

export default function WorkflowsPage() {
  return (
    <main className="app-shell">
      <WorkspaceSidebar />
      <section className="content-area">
        <WorkspaceTopbar current="Workflows" />
        <div className="page-content">
          <section className="panel workflow-panel" aria-labelledby="workflows-title">
            <div className="panel-heading"><div><h1 id="workflows-title">Workflows</h1><p>Create, browse, and edit ComfyUI workflow templates.</p></div></div>
            <WorkflowWorkspace />
          </section>
        </div>
      </section>
    </main>
  );
}
