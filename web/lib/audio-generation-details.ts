import type { ElevenLabsVoice, MediaAsset } from "@/lib/api";
import { ELEVENLABS_MODELS } from "@/lib/elevenlabs-models";

export function audioGenerationDetails(asset: MediaAsset, voices: ElevenLabsVoice[] = []) {
  const status = asset.kind === "audio" ? "Active render audio" : "Saved audio";
  const metadata = asset.generation_metadata;
  if (metadata?.source === "upload") return { voice: "Uploaded audio", api: "", subtitle: `Uploaded audio · ${status}` };
  if (!metadata?.provider && !metadata?.voice_id && !metadata?.model) return { voice: status, api: "", subtitle: `${status} · Voice/API unavailable` };
  const storedName = metadata.voice_name || metadata.settings?.voice_name;
  const voice = typeof storedName === "string" && storedName.trim()
    ? storedName
    : voices.find((item) => item.voice_id === metadata.voice_id)?.name ?? metadata.voice_id ?? "Unknown voice";
  const provider = metadata.provider === "elevenlabs" ? "ElevenLabs" : metadata.provider ?? "Unknown";
  const model = ELEVENLABS_MODELS.find((item) => item.id === metadata.model)?.name ?? metadata.model;
  const compactModel = model?.replace(/^Eleven Multilingual /, "").replace(/^Eleven /, "");
  return { voice, api: [provider, compactModel].filter(Boolean).join(" "), subtitle: [voice, `${provider} API`, model].filter(Boolean).join(" · ") };
}

export function audioGenerationSubtitle(asset: MediaAsset, voices: ElevenLabsVoice[] = []): string {
  return audioGenerationDetails(asset, voices).subtitle;
}
