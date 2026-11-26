import { describe, expect, it } from "vitest";
import type { MediaAsset } from "../lib/api";
import { audioGenerationSubtitle } from "../lib/audio-generation-details";

function asset(metadata: MediaAsset["generation_metadata"]): MediaAsset {
  return { id: "audio-1", job_id: "job-1", kind: "audio", filename: "audio.mp3", content_type: "audio/mpeg", size_bytes: 1, generation_metadata: metadata, download_url: "/audio", created_at: "2026-11-21T00:00:00Z" };
}

describe("audio generation subtitles", () => {
  it("uses the historical voice and API model, not the current selection", () => {
    expect(audioGenerationSubtitle(asset({ source: "tts", voice_name: "Hope", provider: "elevenlabs", voice_id: "old-voice", model: "eleven_v4" }))).toBe("Hope · ElevenLabs API · Eleven v4");
  });
  it("reads voice names from older settings snapshots", () => {
    expect(audioGenerationSubtitle(asset({ provider: "elevenlabs", settings: { voice_name: "Elise" }, model: "eleven_v3" }))).toContain("Elise · ElevenLabs API · Eleven v3");
  });
  it("uses the recorded voice id if no name is available", () => {
    expect(audioGenerationSubtitle(asset({ provider: "elevenlabs", voice_id: "original-voice", model: "custom_model" }))).toContain("original-voice · ElevenLabs API · custom_model");
  });
  it("does not assign a TTS voice to uploaded audio", () => {
    expect(audioGenerationSubtitle(asset({ source: "upload", original_filename: "recording.wav" }))).toBe("Uploaded audio · Active render audio");
  });
  it("does not guess metadata for older assets", () => {
    expect(audioGenerationSubtitle(asset(null))).toBe("Active render audio · Voice/API unavailable");
  });
});
