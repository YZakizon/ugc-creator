import { ContentPromptSettings } from "@/components/content-prompt-settings";
import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";
import { RenderNodeSettings } from "@/components/render-node-settings";

export default function SettingsPage() {
  return (
    <main className="app-shell">
      <WorkspaceSidebar />
      <section className="content-area">
        <WorkspaceTopbar current="Settings" />
        <div className="page-content settings-page">
          <section className="panel" aria-labelledby="settings-title"><div className="panel-heading"><div><h1 id="settings-title">Settings</h1><p>Configure content generation and rendering infrastructure.</p></div></div><ContentPromptSettings /></section>
          <section className="panel" aria-labelledby="render-settings-title"><div className="panel-heading"><div><h2 id="render-settings-title">Rendering</h2><p>Connect and verify rendering infrastructure.</p></div></div><RenderNodeSettings /></section>
        </div>
      </section>
    </main>
  );
}
