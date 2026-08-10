"use client";

import React, { ReactNode, useEffect, useState } from "react";

type DashboardTab = {
  id: string;
  label: string;
  content: ReactNode;
};

const tabIds = new Set(["overview", "create", "content", "library", "profiles", "workflows"]);

function tabForHash(hash: string): string {
  const value = hash.replace(/^#/, "");
  if (value === "new-batch" || value === "new-topic" || value === "create") return "create";
  if (value === "new-profile" || value === "profiles" || value === "characters" || value === "voices") return "profiles";
  if (value === "jobs" || value === "content") return "content";
  if (value === "library") return "library";
  if (value === "workflows") return "workflows";
  return tabIds.has(value) ? value : "overview";
}

export function DashboardTabs({ tabs }: { tabs: DashboardTab[] }) {
  const [activeTab, setActiveTab] = useState("overview");

  useEffect(() => {
    const updateFromHash = () => setActiveTab(tabForHash(window.location.hash));
    updateFromHash();
    window.addEventListener("hashchange", updateFromHash);
    return () => window.removeEventListener("hashchange", updateFromHash);
  }, []);

  function selectTab(id: string) {
    setActiveTab(id);
    window.history.replaceState(null, "", `#${id}`);
  }

  return (
    <>
      <div className="dashboard-tabs" role="tablist" aria-label="Dashboard sections">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            id={`tab-${tab.id}`}
            className={`dashboard-tab ${activeTab === tab.id ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`tab-panel-${tab.id}`}
            onClick={() => selectTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <div
          key={tab.id}
          id={`tab-panel-${tab.id}`}
          className="dashboard-tab-panel"
          role="tabpanel"
          hidden={activeTab !== tab.id}
          aria-labelledby={`tab-${tab.id}`}
        >
          {tab.content}
        </div>
      ))}
    </>
  );
}
