import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";
import { RenderNodeSettings } from "@/components/render-node-settings";

export default function SettingsPage() {
  return (
    <main className="app-shell">
      <WorkspaceSidebar />
      <section className="content-area">
        <WorkspaceTopbar current="Settings" />
        <div className="page-content"><section className="panel" aria-labelledby="settings-title"><div className="panel-heading"><div><h1 id="settings-title">Settings</h1><p>Connect and verify rendering infrastructure.</p></div></div><RenderNodeSettings /></section></div>
      </section>
    </main>
  );
}
