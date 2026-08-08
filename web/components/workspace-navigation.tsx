"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function WorkspaceSidebar() {
  const pathname = usePathname();
  const navClass = (active: boolean) => `nav-item${active ? " active" : ""}`;

  return (
    <aside className="sidebar" aria-label="Primary navigation">
      <Link className="brand" href="/">
        <span className="brand-mark">U</span>
        <span><strong>UGC Creator</strong><small>Studio workspace</small></span>
      </Link>
      <div className="workspace-switcher">
        <span className="avatar avatar-violet">A</span>
        <span><strong>Your Space</strong><small>Personal studio</small></span>
        <span className="chevron">⌄</span>
      </div>
      <nav className="nav-groups">
        <div>
          <p className="nav-label">Workspace</p>
          <Link className={navClass(pathname === "/")} href="/"><span className="nav-icon">▦</span> Dashboard</Link>
          <Link className="nav-item" href="/#create"><span className="nav-icon">＋</span> Create batch</Link>
          <Link className="nav-item" href="/#jobs"><span className="nav-icon">◷</span> Jobs</Link>
          <Link className="nav-item" href="/#library"><span className="nav-icon">▤</span> Library</Link>
        </div>
        <div>
          <p className="nav-label">Configure</p>
          <Link className="nav-item" href="/profiles#new-profile"><span className="nav-icon">◉</span> Characters</Link>
          <Link className={navClass(pathname === "/voice-profiles")} href="/voice-profiles"><span className="nav-icon">◒</span> Voice profiles</Link>
          <Link className={navClass(pathname === "/profiles")} href="/profiles"><span className="nav-icon">✦</span> Profiles</Link>
          <Link className={navClass(pathname === "/workflows")} href="/workflows"><span className="nav-icon">⌘</span> Workflows</Link>
        </div>
      </nav>
      <div className="sidebar-bottom">
        <Link className={navClass(pathname === "/settings")} href="/settings"><span className="nav-icon">⚙</span> Settings</Link>
        <div className="user-card">
          <span className="avatar avatar-orange">A</span>
          <span><strong>Your Name</strong><small>your@email.com</small></span>
          <span className="more">•••</span>
        </div>
      </div>
    </aside>
  );
}

export function WorkspaceTopbar({ current }: { current: string }) {
  return (
    <header className="topbar">
      <div className="breadcrumbs"><span>Workspace</span><span>/</span><strong>{current}</strong></div>
      <div className="topbar-actions">
        <label className="search-box"><span aria-hidden="true">⌕</span><input aria-label="Search workspace" placeholder="Search workspace" /><kbd>⌘ K</kbd></label>
        <button className="icon-button" aria-label="View notifications">♢</button>
        <Link className="button button-primary button-small" href="/#create"><span>＋</span> New batch</Link>
      </div>
    </header>
  );
}
