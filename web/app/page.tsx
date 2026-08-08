import React from "react";
import Link from "next/link";

import { CreateBatchForm } from "@/components/create-batch-form";
import { CurrentDate, DashboardStats, RecentJobs } from "@/components/dashboard-live-data";
import { DashboardTabs } from "@/components/dashboard-tabs";
import { RenderProfileSetup } from "@/components/render-profile-setup";
import { WorkflowTemplateSetup } from "@/components/workflow-template-setup";
import { WorkspaceSidebar, WorkspaceTopbar } from "@/components/workspace-navigation";

type HealthResponse = {
  status: string;
};

async function getApiHealth(): Promise<HealthResponse | null> {
  const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

  try {
    const response = await fetch(`${apiBaseUrl}/health`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return null;
    }

    return (await response.json()) as HealthResponse;
  } catch {
    return null;
  }
}

export default async function HomePage() {
  const health = await getApiHealth();
  const apiConnected = health?.status === "ok";

  return (
    <main className="app-shell">
      <WorkspaceSidebar />

      <section className="content-area">
        <WorkspaceTopbar current="Dashboard" />

        <div className="page-content">
          <DashboardTabs tabs={[
            { id: "overview", label: "Overview", content: <>
              <section className="welcome-row">
                <div><CurrentDate /><h1 id="page-title">Good morning, Your Name <span aria-hidden="true">✦</span></h1><p className="lede">Turn a good idea into a scroll-stopping video.</p></div>
                <div className="connection-pill" role="status"><span className={apiConnected ? "pulse-dot" : "pulse-dot offline"} />API {apiConnected ? "connected" : "offline"}</div>
              </section>
              <section className="hero-card" aria-labelledby="create-title">
                <div className="hero-copy"><span className="hero-kicker">CREATE SOMETHING NEW</span><h2 id="create-title">What do you want to talk about?</h2><p>Start with one idea or paste a list of topics. We&apos;ll turn each one into a complete UGC video.</p><div className="hero-actions"><Link className="button button-light" href="#new-batch">Start a new batch <span>→</span></Link><Link className="text-link light-link" href="#jobs">View recent jobs <span>↗</span></Link></div></div>
                <div className="hero-art" aria-hidden="true"><div className="hero-orb orb-one" /><div className="hero-orb orb-two" /><div className="hero-note note-one"><span>✦</span> Hook</div><div className="hero-note note-two"><span>◒</span> Voice</div><div className="hero-note note-three"><span>▶</span> Video</div><div className="hero-phone"><div className="phone-screen"><span>your story</span><b>starts here.</b><i>▶</i></div></div></div>
              </section>
              <DashboardStats />
              <div className="dashboard-grid"><section className="panel jobs-panel" aria-labelledby="overview-jobs-title"><div className="panel-heading"><div><h2 id="overview-jobs-title">Recent jobs</h2><p>Your latest content and render activity</p></div><Link className="text-link" href="#jobs">View all <span>→</span></Link></div><RecentJobs /></section><section className="panel health-panel" aria-labelledby="health-title"><div className="panel-heading"><div><h2 id="health-title">Pipeline health</h2><p>Only the API connection is checked here.</p></div><span className="healthy-label"><span className={apiConnected ? "pulse-dot" : "pulse-dot offline"} /> {apiConnected ? "API connected" : "API offline"}</span></div><div className="health-list"><div className="health-row"><span className="service-badge blue">⌁</span><span><strong>API service</strong><small>Request routing and jobs</small></span><b className={apiConnected ? "health-ok" : "health-warning"}>{apiConnected ? "Operational" : "Offline"}</b></div><div className="health-row"><span className="service-badge purple">◈</span><span><strong>Render worker</strong><small>Async generation queue</small></span><b className="health-unknown">Not checked</b></div><div className="health-row"><span className="service-badge green">▣</span><span><strong>Media storage</strong><small>Assets and finished videos</small></span><b className="health-unknown">Not checked</b></div></div></section></div>
            </> },
            { id: "create", label: "Create batch", content: <CreateBatchForm /> },
            { id: "jobs", label: "Jobs", content: <section className="panel jobs-panel" aria-labelledby="jobs-title"><div className="panel-heading"><div><h2 id="jobs-title">Jobs</h2><p>Track content and render activity.</p></div></div><RecentJobs /></section> },
            { id: "library", label: "Library", content: <section className="panel compact-empty empty-state" aria-labelledby="library-title"><h2 id="library-title">Output library</h2><p>Completed videos will appear here after the render pipeline is connected.</p></section> },
            { id: "profiles", label: "Profiles", content: <section className="panel profile-panel" aria-labelledby="profiles-title"><div className="panel-heading"><div><h2 id="profiles-title">Render profiles</h2><p>Reusable setups for your characters and scenes.</p></div></div><RenderProfileSetup /></section> },
            { id: "workflows", label: "Workflows", content: <section className="panel workflow-panel" aria-labelledby="workflows-title"><div className="panel-heading"><div><h2 id="workflows-title">ComfyUI workflows</h2><p>Import an API workflow and map semantic inputs.</p></div></div><WorkflowTemplateSetup /></section> },
          ]} />
        </div>
      </section>
    </main>
  );
}
