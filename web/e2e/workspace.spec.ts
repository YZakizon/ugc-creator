import { expect, test } from "@playwright/test";

const workflow = JSON.stringify({
  "1": { class_type: "LoadImage", inputs: { image: "source.png" } },
  "2": { class_type: "LoadAudio", inputs: { audio: "voice.wav" } },
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

  test("imports a workflow, creates a profile, and creates a multi-topic batch", async ({ page }) => {
    await page.getByRole("link", { name: "Workflows" }).click();
    await expect(page.getByRole("heading", { name: "Workflows" })).toBeVisible();
    await page.getByRole("link", { name: "Import workflow" }).first().click();
    await expect(page).toHaveURL(/#workflows$/);
    await page.getByLabel("Template name").fill("Shelf workflow");
    await page.getByLabel("ComfyUI API workflow JSON").fill(workflow);
    const workflowResponse = page.waitForResponse((response) => response.url().includes("workflow-templates") && response.request().method() === "POST");
    await page.getByRole("button", { name: "Import workflow" }).click();
    expect((await workflowResponse).status()).toBe(201);
    await expect(page.getByText("Workflow version 1 saved successfully.")).toBeVisible();

    await page.locator('a[href="/profiles"]').click();
    await page.getByRole("tab", { name: "Create profile" }).click();
    await page.getByLabel("Profile name").fill("Elena Shelf");
    await page.getByLabel("Character name").fill("Elena");
    await page.getByLabel("Voice profile").fill("Elena voice");
    await page.getByLabel("ElevenLabs voice ID").fill("voice-elena");
    await page.getByLabel("Workflow template").selectOption({ label: /Shelf workflow/ });
    await page.getByRole("button", { name: "Create profile" }).click();
    await expect(page.getByText("Render profile created successfully.")).toBeVisible();

    await page.getByRole("link", { name: "Create batch" }).click();
    await page.getByLabel("Batch name").fill("Tuesday ideas");
    await page.getByLabel("Topics").fill("Burnout is not laziness\nA reminder for overthinkers");
    await page.getByLabel("Render profile").selectOption({ label: "Elena Shelf" });
    await page.getByRole("button", { name: "Create batch" }).click();
    await expect(page.getByText("Batch created successfully.")).toBeVisible();
    await page.getByRole("tab", { name: "Jobs" }).click();
    await expect(page.getByText("Burnout is not laziness")).toBeVisible();
    const generateResponse = page.waitForResponse((response) => response.url().includes("generate-content") && response.request().method() === "POST");
    await page.getByRole("button", { name: "Generate content" }).first().click();
    expect((await generateResponse).status()).toBe(202);
    await expect.poll(async () => {
      await page.reload();
      await page.getByRole("tab", { name: "Jobs" }).click();
      return await page.locator(".job-row").first().innerText();
    }, { timeout: 20_000, intervals: [1000, 2000] }).toContain("content ready");
  });
});
