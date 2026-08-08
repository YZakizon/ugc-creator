import { VoiceProfileSetup } from "@/components/voice-profile-setup";
import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";

export default function VoiceProfilesPage() {
  return <main className="app-shell">
    <WorkspaceSidebar />
    <section className="content-area">
      <WorkspaceTopbar current="Voice profiles" />
      <div className="page-content"><section className="panel profile-panel"><div className="panel-heading"><div><h1>Voice profiles</h1><p>Create reusable ElevenLabs voices and tune their synthesis parameters.</p></div></div><VoiceProfileSetup /></section></div>
    </section>
  </main>;
}
