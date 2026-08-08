import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";

export default function SettingsPage() {
  return (
    <main className="app-shell">
      <WorkspaceSidebar />
      <section className="content-area">
        <WorkspaceTopbar current="Settings" />
        <div className="page-content"><section className="panel compact-empty empty-state" aria-labelledby="settings-title"><h1 id="settings-title">Settings</h1><p>Workspace and provider settings will appear here.</p></section></div>
      </section>
    </main>
  );
}
