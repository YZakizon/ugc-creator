import { expect, test } from "@playwright/test";

function wavBuffer(durationSeconds = 1, sampleRate = 8_000) {
  const dataSize = durationSeconds * sampleRate * 2;
  const buffer = Buffer.alloc(44 + dataSize);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVEfmt ", 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(dataSize, 40);
  return buffer;
}

const workflow = JSON.stringify({
  "1": { class_type: "LoadImage", inputs: { image: "source.png" } },
  "2": { class_type: "LoadAudio", inputs: { audio: "voice.wav" } },
  "3": { class_type: "PrimitiveFloat", _meta: { title: "Duration" }, inputs: { value: 30 } },
  "4": { class_type: "PrimitiveStringMultiline", _meta: { title: "LTX 2.3 Prompt" }, inputs: { value: "A creator speaks." } },
});

test.describe("workspace customer journeys", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("status")).toContainText("API connected");
  });

  test("covers dashboard tabs, empty library, and settings/navigation", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Good morning, Your Name" })).toBeVisible();
    await page.getByRole("tab", { name: "Library" }).click();
    await expect(page.getByRole("heading", { name: "Output library" })).toBeVisible();
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await page.getByRole("link", { name: "Dashboard" }).click();
    await expect(page.getByRole("heading", { name: "Good morning, Your Name" })).toBeVisible();
  });

  test("switches between generated speech preview and history", async ({ page }) => {
    const profileName = `Playwright voice ${Date.now()}`;
    const createResponse = await page.request.post("/api/v1/voice-profiles", {
      data: {
        name: profileName,
        provider: "elevenlabs",
        provider_voice_id: "playwright-voice-id",
        provider_model: "eleven_multilingual_v2",
        speed: 1,
        stability: 0.5,
        similarity: 0.75,
        style_exaggeration: 0.5,
        extra_settings: { voice_name: "Playwright Voice" },
      },
    });
    expect(createResponse.status()).toBe(201);

    await page.route("**/api/v1/voice-profiles/*/previews", async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [{
            id: "playwright-preview",
            voice_profile_id: "playwright-profile",
            text: "Playwright generated speech history check",
            status: "completed",
            provider: "elevenlabs",
            provider_request_id: "fake-request",
            generated_usage_units: 42,
            account_used_units: 100,
            account_limit_units: 10000,
            account_remaining_units: 9900,
            usage_resets_at_unix: null,
            usage_unit: "characters",
            content_type: "audio/mpeg",
            filename: "preview.mp3",
            error_message: null,
            download_url: "/api/v1/voice-previews/playwright-preview/audio",
            created_at: "2026-08-09T07:00:00Z",
            updated_at: "2026-08-09T07:00:01Z",
          }],
          total: 1,
        }),
      });
    });

    await page.goto("/voice-profiles");
    await page.getByRole("button", { name: `Show ${profileName} details` }).click();

    const tabList = page.getByRole("tablist", { name: "Generated speech sections" });
    const previewTab = page.getByRole("tab", { name: "Preview" });
    const historyTab = page.getByRole("tab", { name: "History" });
    const previewPanel = page.getByRole("tabpanel", { name: "Preview" });

    await expect(previewTab).toHaveAttribute("aria-selected", "true");
    await expect(previewPanel.getByRole("heading", { name: "Preview to generate speech" })).toBeVisible();
    const tabBox = await tabList.boundingBox();
    const panelBox = await previewPanel.boundingBox();
    expect(tabBox).not.toBeNull();
    expect(panelBox).not.toBeNull();
    expect((panelBox?.y ?? 0) > (tabBox?.y ?? 0) + (tabBox?.height ?? 0)).toBe(true);
    expect(Math.abs((panelBox?.width ?? 0) - (tabBox?.width ?? 0))).toBeLessThan(2);

    await historyTab.click();
    await expect(historyTab).toHaveAttribute("aria-selected", "true");
    const historyPanel = page.getByRole("tabpanel", { name: "History" });
    await expect(historyPanel.getByRole("heading", { name: "Generated speech history" })).toBeVisible();
    await expect(previewPanel).toBeHidden();
    const downloadBox = await historyPanel.getByRole("link", { name: "Download audio" }).boundingBox();
    const deleteBox = await historyPanel.getByRole("button", { name: "Delete generated speech" }).boundingBox();
    expect(downloadBox).not.toBeNull();
    expect(deleteBox).not.toBeNull();
    expect(downloadBox?.width).toBe(deleteBox?.width);
    expect(downloadBox?.height).toBe(deleteBox?.height);
  });

  test("creates a topic with repeatable numbered content, speech, video, and deletion", async ({ page }) => {
    test.setTimeout(120_000);
    const suffix = `pw-${Date.now().toString(36)}`;
    const workflowName = `Shelf workflow ${suffix}`;
    const voiceProfileName = `Elena voice ${suffix}`;
    const renderProfileName = `Elena Shelf ${suffix}`;
    const nodeName = `Fake ComfyUI ${suffix}`;
    const topicName = `Burnout is not laziness ${suffix}`;
    const mediaBase = `burnout-is-not-laziness-${suffix}`;
    await page.getByRole("link", { name: "Workflows" }).click();
    await expect(page.getByRole("heading", { name: "Workflows" })).toBeVisible();
    await page.getByRole("tab", { name: "Create workflow" }).click();
    await page.getByLabel("Template name").fill(workflowName);
    await page.getByLabel("ComfyUI API workflow JSON").fill(workflow);
    await page.getByLabel("Default source image").setInputFiles({ name: "source.png", mimeType: "image/png", buffer: Buffer.from("fake-image") });
    await expect(page.getByText("Current file: source.png")).toBeVisible();
    await page.getByLabel("Default audio").setInputFiles({ name: "voice.wav", mimeType: "audio/wav", buffer: Buffer.from("fake-audio") });
    await expect(page.getByText("Current file: voice.wav")).toBeVisible();
    await page.getByRole("button", { name: /Image source/i }).click();
    await expect(page.getByRole("button", { name: /SOURCE_IMAGE/ })).toBeVisible();
    await page.getByRole("button", { name: /Audio source/i }).click();
    await expect(page.getByRole("button", { name: /\{\{AUDIO\}\}/ })).toBeVisible();
    await page.getByRole("button", { name: /Duration.*30/i }).click();
    await page.getByRole("button", { name: /AUDIO_DURATION/ }).click();
    await page.locator(".workflow-ltx-control")
      .filter({ hasText: "Duration" })
      .locator("input")
      .fill("{{AUDIO_DURATION + 1}}");
    await expect(page.getByLabel("ComfyUI API workflow JSON")).toHaveValue(/\{\{AUDIO_DURATION \+ 1\}\}/);

    const imageUpload = page.getByLabel("Default source image").locator("..");
    const audioUpload = page.getByLabel("Default audio").locator("..");
    await imageUpload.getByRole("button", { name: "Remove", exact: true }).click();
    await audioUpload.getByRole("button", { name: "Remove", exact: true }).click();
    await expect(imageUpload).toContainText("No default image saved");
    await expect(audioUpload).toContainText("No default audio saved");
    await page.getByLabel("Default source image").setInputFiles({ name: "source.png", mimeType: "image/png", buffer: Buffer.from("fake-image") });
    await page.getByLabel("Default audio").setInputFiles({ name: "voice.wav", mimeType: "audio/wav", buffer: Buffer.from("fake-audio") });
    const workflowResponse = page.waitForResponse((response) => response.url().includes("workflow-templates") && response.request().method() === "POST");
    await page.getByRole("button", { name: "Import workflow" }).click();
    expect((await workflowResponse).status()).toBe(201);
    await expect(page.getByText("Workflow imported successfully.")).toBeVisible();

    await page.getByRole("link", { name: "Voice profiles" }).click();
    await page.getByRole("tab", { name: "Create voice profile" }).click();
    await page.getByLabel("Voice profile name").fill(voiceProfileName);
    await page.getByLabel("Voice name").fill("Elena");
    await page.getByLabel("Voice ID").fill("voice-elena");
    await page.getByRole("button", { name: "Create voice profile" }).click();
    await expect(page.getByText("Voice profile created.")).toBeVisible();

    await page.locator('a[href="/profiles"]').click();
    await page.getByRole("tab", { name: "Create profile" }).click();
    await page.getByLabel("Profile name").fill(renderProfileName);
    await page.getByLabel("Character").fill("Elena");
    const voiceOption = page.getByLabel("Voice profile").locator("option").filter({ hasText: voiceProfileName });
    const voiceProfileId = await voiceOption.getAttribute("value") ?? "";
    await page.getByLabel("Voice profile").selectOption(voiceProfileId);
    const workflowOption = page.getByLabel("Workflow template").locator("option").filter({ hasText: workflowName });
    const workflowTemplateId = await workflowOption.getAttribute("value") ?? "";
    await page.getByLabel("Workflow template").selectOption(workflowTemplateId);
    await page.getByRole("button", { name: "Create profile" }).click();
    await expect(page.getByText("Render profile created successfully.")).toBeVisible();

    await page.getByRole("link", { name: "Voice profiles" }).click();
    await page.getByRole("tab", { name: "Voice profiles" }).click();
    await page.getByRole("button", { name: `Show ${voiceProfileName} details` }).click();
    await page.getByPlaceholder("Enter text to generate speech…").fill("This is a generated speech preview.");
    await page.getByRole("button", { name: "Generate speech" }).click();
    await expect(page.getByText("completed", { exact: true })).toBeVisible({ timeout: 20_000 });
    const speechDownload = page.getByRole("link", { name: "Download audio" });
    const speechResponse = await page.request.get(await speechDownload.getAttribute("href") ?? "");
    expect(speechResponse.status()).toBe(200);

    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByLabel("Node name").fill(nodeName);
    await page.getByLabel("ComfyUI URL").fill("http://fake-comfyui-test:8188");
    await page.getByRole("button", { name: "Add render node" }).click();
    await expect(page.getByText("Render node saved.")).toBeVisible();
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(page.getByText("ComfyUI is connected.")).toBeVisible();

    await page.getByRole("link", { name: "Create topic" }).click();
    await page.getByRole("textbox", { name: "Topic", exact: true }).fill(topicName);
    await page.locator(".batch-form select").selectOption({ label: renderProfileName });
    await page.getByRole("button", { name: "Create topic" }).click();
    await expect(page.getByText("Topic created successfully.")).toBeVisible();
    await page.getByRole("tab", { name: "Content" }).click();
    const contentPanel = page.locator("#tab-panel-content");
    const topicCard = contentPanel.locator(".topic-history-card").filter({ hasText: topicName });
    await topicCard.locator(":scope > summary").click();
    const firstJob = topicCard.locator(".job-card").filter({ hasText: "Content 1" });
    await expect(firstJob).toBeVisible();
    await firstJob.locator(".job-card-summary").click();
    const generateResponse = page.waitForResponse((response) => response.url().includes("generate-content") && response.request().method() === "POST");
    await firstJob.getByRole("button", { name: "Generate content" }).click();
    expect((await generateResponse).status()).toBe(202);
    await expect.poll(async () => {
      await page.reload();
      await page.getByRole("tab", { name: "Content" }).click();
      await topicCard.locator(":scope > summary").click();
      return (await firstJob.innerText()).toLowerCase();
    }, { timeout: 20_000, intervals: [1000, 2000] }).toContain("content ready");

    await firstJob.locator(".job-card-summary").click();
    await expect(firstJob.getByRole("combobox", { name: "Voice profile", exact: true })).toHaveValue(voiceProfileId);
    await expect(firstJob.getByRole("link", { name: "Open voice profile details" })).toHaveAttribute("href", `/voice-profiles#voice-profile-${voiceProfileId}`);
    const jobSpeechResponse = page.waitForResponse((response) => response.url().includes("generate-tts") && response.request().method() === "POST");
    await firstJob.getByRole("button", { name: "Generate speech" }).click();
    expect((await jobSpeechResponse).status()).toBe(202);
    await expect.poll(async () => {
      await page.reload();
      await page.getByRole("tab", { name: "Content" }).click();
      await topicCard.locator(":scope > summary").click();
      return (await firstJob.innerText()).toLowerCase();
    }, { timeout: 20_000, intervals: [1000, 2000] }).toContain("ready to render");

    await firstJob.locator(".job-card-summary").click();
    await expect(firstJob.getByRole("link", { name: "Download generated speech" })).toBeVisible();
    await firstJob.getByRole("tab", { name: "Render ComfyUI" }).click();
    await expect(firstJob.getByRole("combobox", { name: "Workflow", exact: true })).toHaveValue(workflowTemplateId);
    await expect(firstJob.getByRole("link", { name: "Open workflow details" })).toHaveAttribute("href", `/workflows#workflow-${workflowTemplateId}`);
    await expect(firstJob.locator(".job-render-audio").getByText(`${mediaBase}_content1_0001.wav`)).toBeVisible();
    await expect(firstJob.getByRole("link", { name: "Download render audio" })).toHaveCount(0);
    const audioUploadResponse = page.waitForResponse((response) => response.url().includes(`/api/v1/jobs/`) && response.url().endsWith("/audio") && response.request().method() === "POST");
    await firstJob.getByLabel("Upload different audio").setInputFiles({ name: "replacement.wav", mimeType: "audio/wav", buffer: wavBuffer() });
    expect((await audioUploadResponse).status()).toBe(200);
    await expect(firstJob.locator(".job-render-audio").getByText(`${mediaBase}_content1_0002.wav`)).toBeVisible();
    await firstJob.getByRole("button", { name: "Render with ComfyUI" }).click();
    await expect.poll(async () => (await firstJob.innerText()).toLowerCase(), {
      timeout: 20_000,
      intervals: [500, 1000],
    }).toContain("rendering");
    await expect.poll(async () => (await firstJob.innerText()).toLowerCase(), {
      timeout: 30_000,
      intervals: [1000, 2000],
    }).toContain("completed");
    await expect(firstJob.getByRole("button", { name: `Preview ${mediaBase}_content1_0001.mp4` })).toBeVisible();
    await expect(firstJob.getByRole("link", { name: `Download ${mediaBase}_content1_0001.mp4` })).toBeVisible();
    await expect(firstJob.getByRole("button", { name: `Delete ${mediaBase}_content1_0001.mp4` })).toBeVisible();
    await expect(firstJob.getByRole("combobox", { name: "Render profile", exact: true })).toBeEnabled();
    await expect(firstJob.getByRole("combobox", { name: "Workflow", exact: true })).toBeEnabled();
    await firstJob.getByRole("tab", { name: "Generate speech" }).click();
    await expect(firstJob.getByRole("combobox", { name: "Voice profile", exact: true })).toBeEnabled();
    await firstJob.getByRole("tab", { name: "Render ComfyUI" }).click();
    await expect(firstJob.getByRole("button", { name: "Show ComfyUI Job ID" })).toHaveCount(1);
    await expect(firstJob.getByRole("button", { name: "Show Render attempt ID" })).toHaveCount(0);

    const rerenderResponse = page.waitForResponse((response) => response.url().includes("/render?node_id=") && response.request().method() === "POST");
    await firstJob.getByRole("button", { name: "Generate new video" }).click();
    expect((await rerenderResponse).status()).toBe(202);
    await expect(firstJob.getByRole("link", { name: `Download ${mediaBase}_content1_0002.mp4` })).toBeVisible({ timeout: 30_000 });

    await page.getByRole("tab", { name: "Library" }).click();
    await expect(page.getByLabel("Output library").getByText(`${mediaBase}_content1_0001.mp4`, { exact: true })).toBeVisible();
    await expect(page.getByLabel("Output library").getByText(`${mediaBase}_content1_0002.mp4`, { exact: true })).toBeVisible();
    const videoDownload = page.getByRole("link", { name: "Download video" }).first();
    const videoResponse = await page.request.get(await videoDownload.getAttribute("href") ?? "");
    expect(videoResponse.status()).toBe(200);

    await page.getByRole("tab", { name: "Content" }).click();
    const moreContentResponse = page.waitForResponse((response) => response.url().includes("/topics/") && response.url().endsWith("/contents") && response.request().method() === "POST");
    await topicCard.getByRole("button", { name: /Generate more content/ }).click();
    expect((await moreContentResponse).status()).toBe(202);
    const secondJob = topicCard.locator(".job-card").filter({ hasText: "Content 2" });
    await expect(secondJob).toBeVisible();
    await expect.poll(async () => (await secondJob.innerText()).toLowerCase(), {
      timeout: 20_000,
      intervals: [1000, 2000],
    }).toContain("content ready");
    await secondJob.locator(".job-card-summary").click();
    const deleteContentResponse = page.waitForResponse((response) => response.url().includes("/api/v1/contents/") && response.request().method() === "DELETE");
    await secondJob.getByRole("button", { name: /Delete content/ }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete content" }).click();
    expect((await deleteContentResponse).status()).toBe(204);
    await expect(secondJob).toHaveCount(0);

    const deleteTopicResponse = page.waitForResponse((response) => response.url().includes("/api/v1/topics/") && response.request().method() === "DELETE");
    await topicCard.getByRole("button", { name: `Delete topic ${topicName}` }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete topic" }).click();
    expect((await deleteTopicResponse).status()).toBe(204);
    await expect(topicCard).toHaveCount(0);
  });
});
