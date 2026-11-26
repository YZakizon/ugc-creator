import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { VoiceCatalogPreview } from "../components/voice-catalog-preview";
import { loadVoiceSample } from "../lib/voice-preview-cache";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("caches voice samples across component mounts and never calls synthesis", async () => {
  const saved = new Map<string, Response>();
  vi.stubGlobal("caches", { open: vi.fn().mockResolvedValue({
    match: async (key: string) => saved.get(key)?.clone(),
    put: async (key: string, value: Response) => { saved.set(key, value); },
    keys: async () => Array.from(saved.keys()),
    delete: async (key: string) => saved.delete(key),
  }) });
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("audio", { headers: { "Content-Type": "audio/mpeg" } }));
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:sample");
    static revokeObjectURL = vi.fn();
  });
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  const voice = { voice_id: "hope", name: "Hope", preview_url: "https://example.test/hope.mp3", category: null, description: null };
  const mount = () => render(<QueryClientProvider client={new QueryClient()}><VoiceCatalogPreview voice={voice} /></QueryClientProvider>);
  const first = mount();
  fireEvent.click(screen.getByRole("button", { name: "Preview Hope" }));
  await waitFor(() => expect(play).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Preview Hope" }));
  await waitFor(() => expect(play).toHaveBeenCalledTimes(2));
  first.unmount();
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Preview Hope" }));
  await waitFor(() => expect(play).toHaveBeenCalledTimes(3));
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith(voice.preview_url, { cache: "force-cache", credentials: "omit" });
});

it("still plays when persistent cache is unavailable", async () => {
  vi.stubGlobal("caches", { open: vi.fn().mockRejectedValue(new Error("quota")) });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("audio"));
  expect(await (await loadVoiceSample("https://example.test/sample.mp3")).text()).toBe("audio");
});
