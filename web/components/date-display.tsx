"use client";

import React, { useEffect, useState } from "react";

export function HumanDate({ value }: { value: string }) {
  const [display, setDisplay] = useState("Date");
  const [title, setTitle] = useState("");

  useEffect(() => {
    function update() {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return;
      setTitle(new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date));
      setDisplay(relativeTime(date));
    }
    update();
    const interval = window.setInterval(update, 60_000);
    return () => window.clearInterval(interval);
  }, [value]);

  return <time dateTime={value} title={title} suppressHydrationWarning>{display}</time>;
}

function relativeTime(date: Date): string {
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} hr ago`;
  if (seconds < 604_800) return `${Math.floor(seconds / 86_400)} day${Math.floor(seconds / 86_400) === 1 ? "" : "s"} ago`;
  if (seconds < 2_592_000) return `${Math.floor(seconds / 604_800)} wk ago`;
  if (seconds < 31_536_000) return `${Math.floor(seconds / 2_592_000)} mo ago`;
  return `${Math.floor(seconds / 31_536_000)} yr ago`;
}
