const CACHE_NAME = "ugc-voice-samples-v1";
const MAX_SAMPLES = 30;

/** Public catalog samples only; generated speech stays in server media storage. */
export async function loadVoiceSample(url: string): Promise<Blob> {
  let cache: Cache | undefined;
  try {
    if (typeof caches !== "undefined") {
      cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(url);
      if (cached) return await cached.blob();
    }
  } catch {
    // Private browsing or a full disk must not prevent preview playback.
    cache = undefined;
  }
  const response = await fetch(url, { cache: "force-cache", credentials: "omit" });
  if (!response.ok) throw new Error("Voice preview is unavailable. Try again.");
  const blob = await response.blob();
  if (cache) {
    try {
      await cache.put(url, new Response(blob, { headers: { "Content-Type": blob.type } }));
      const keys = await cache.keys();
      for (const key of keys.slice(0, Math.max(0, keys.length - MAX_SAMPLES))) await cache.delete(key);
    } catch {
      // Playback still works if persistent caching is unavailable.
    }
  }
  return blob;
}
