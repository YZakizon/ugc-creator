import { expect, test } from "@playwright/test";

test("ElevenLabs models adapt controls and voice samples remain cached after reload", async ({ page }) => {
  let downloads = 0;
  const wav = Buffer.alloc(44 + 1600);
  wav.write("RIFF", 0); wav.writeUInt32LE(wav.length - 8, 4);
  wav.write("WAVEfmt ", 8); wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
  wav.write("data", 36); wav.writeUInt32LE(1600, 40);
  await page.route("**/voice-test-sample.wav", async (route) => {
    downloads += 1;
    await route.fulfill({ contentType: "audio/wav", body: wav });
  });
  await page.route("**/api/v1/**", async (route) => {
    const url = route.request().url();
    // No paid synthesis or persistent data changes are permitted in this test.
    expect(route.request().method()).toBe("GET");
    let data: object = { items: [], total: 0 };
    if (url.includes("/tts-providers/elevenlabs/voices")) data = { items: [{ voice_id: "cached-hope", name: "Cached Hope", preview_url: new URL("/voice-test-sample.wav", url).href, category: "generated", description: null }], total: 1 };
    if (url.includes("/tts-providers/elevenlabs/usage")) data = { provider: "elevenlabs", configured: true, used_units: 0, limit_units: 100, remaining_units: 100, unit: "characters" };
    await route.fulfill({ json: data });
  });
  await page.goto("/voice-profiles");
  await page.getByRole("tab", { name: "Create voice profile" }).click();
  await expect(page.getByRole("slider", { name: "Speed", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Model", exact: true }).selectOption("eleven_v3");
  await expect(page.getByRole("slider", { name: "Speed", exact: true })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "Stability", exact: true })).toHaveValue("50");
  await page.getByRole("combobox", { name: "Model", exact: true }).selectOption("eleven_v4");
  await expect(page.getByRole("slider", { name: "Similarity", exact: true })).toBeVisible();
  await expect(page.getByRole("slider", { name: "Style Exaggeration", exact: true })).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath("elevenlabs-v4.png"), fullPage: true });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (attempt) {
      await page.reload();
      await page.getByRole("tab", { name: "Create voice profile" }).click();
    }
    await page.getByRole("button", { name: "Choose from ElevenLabs My Voices" }).click();
    await page.getByRole("button", { name: "Preview Cached Hope", exact: true }).click();
    const audio = page.getByRole("dialog", { name: "ElevenLabs My Voices" }).locator("audio");
    await expect(audio).toHaveAttribute("src", /^blob:/);
    await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.readyState)).toBeGreaterThan(0);
    await expect(page.getByRole("dialog", { name: "ElevenLabs My Voices" }).getByRole("alert")).toHaveCount(0);
    expect(downloads).toBe(1);
  }
});
