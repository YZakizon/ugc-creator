import { RenderProfileSetup } from "@/components/render-profile-setup";
import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";

export default function ProfilesPage() {
  return (
    <main className="app-shell">
      <WorkspaceSidebar />
      <section className="content-area">
        <WorkspaceTopbar current="Profiles" />
        <div className="page-content"><section className="panel profile-panel" aria-labelledby="profiles-title"><div className="panel-heading"><div><h1 id="profiles-title">Profiles</h1><p>Browse saved render profiles or create a new one.</p></div></div><RenderProfileSetup /></section></div>
      </section>
    </main>
  );
}
