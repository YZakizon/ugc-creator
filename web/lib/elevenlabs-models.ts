export const ELEVENLABS_MODELS = [
  { id: "eleven_multilingual_v2", name: "Eleven Multilingual v2" },
  { id: "eleven_turbo_v2_5", name: "Eleven Turbo v2.5" },
  { id: "eleven_v3", name: "Eleven v3" },
  { id: "eleven_v4", name: "Eleven v4" },
  { id: "eleven_v4_turbo", name: "Eleven v4 Turbo" },
];

export function elevenLabsCapabilities(model: string) {
  const v3 = model === "eleven_v3";
  const v4 = model === "eleven_v4" || model === "eleven_v4_turbo";
  return { speed: !v3 && !v4, similarity: !v3, style: !v3 && !v4, speakerBoost: !v3 && !v4, v3, v4 };
}
