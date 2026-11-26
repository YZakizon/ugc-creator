import React from "react";

import { CreatedVideosPage } from "@/components/create-video-panel";
import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";

export default function CreatedVideosRoute() {
  return (
    <main className="app-shell">
      <WorkspaceSidebar />
      <section className="content-area">
        <WorkspaceTopbar current="Created Videos" />
        <div className="page-content">
          <CreatedVideosPage />
        </div>
      </section>
    </main>
  );
}
