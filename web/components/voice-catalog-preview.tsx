"use client";

import React, { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ElevenLabsVoice } from "@/lib/api";
import { loadVoiceSample } from "@/lib/voice-preview-cache";

export function VoiceCatalogPreview({ voice }: { voice: ElevenLabsVoice }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const mountedRef = useRef(false);
  const sampleUrlRef = useRef(voice.preview_url);
  sampleUrlRef.current = voice.preview_url;
  const [error, setError] = useState(false);
  const sample = useQuery({
    queryKey: ["voice-sample", voice.preview_url],
    queryFn: () => loadVoiceSample(voice.preview_url!),
    enabled: false,
    staleTime: Infinity,
    gcTime: 30 * 60_000,
    retry: false,
  });
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    };
  }, [voice.preview_url]);

  async function playPreview() {
    setError(false);
    const result = sample.data ? { data: sample.data } : await sample.refetch();
    if (!mountedRef.current || sampleUrlRef.current !== voice.preview_url) return;
    if (!result.data || !audioRef.current) { setError(true); return; }
    if (!objectUrlRef.current) objectUrlRef.current = URL.createObjectURL(result.data);
    document.querySelectorAll<HTMLAudioElement>("audio[data-voice-catalog-preview]").forEach((audio) => {
      if (audio !== audioRef.current) { audio.pause(); audio.currentTime = 0; }
    });
    audioRef.current.src = objectUrlRef.current;
    try { await audioRef.current.play(); } catch { setError(true); }
  }

  return <><audio ref={audioRef} data-voice-catalog-preview preload="none" controls={Boolean(sample.data)} /><button className="voice-preview-icon" type="button" disabled={sample.isFetching || !voice.preview_url} aria-label={`Preview ${voice.name}`} title={`Preview ${voice.name} (cached)`} onClick={() => void playPreview()}>{sample.isFetching ? <span className="inline-spinner" /> : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7L8 5Z" /></svg>}</button>{error && <small role="alert">Voice preview unavailable. Try again.</small>}</>;
}
