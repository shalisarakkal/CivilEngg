import { readFileSync } from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";

/**
 * Exercises the Phase 9 UI additions (key-phrase display, semantic-type
 * badges, and plan-sheet snippets) against the real backend, following the
 * same real-backend approach as full-workflow.spec.ts.
 */

function uniqueName(label: string): string {
  return `${label} ${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

const dxfFixture = readFileSync(path.join(__dirname, "fixtures", "phase9-sample.dxf"));

test("key phrases extracted from narrative text are shown on their entity cards", async ({ page }) => {
  const projectName = uniqueName("Phase 9 Key Phrases");

  await page.goto("/");
  await page.getByLabel("New project").fill(projectName);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "The required setback is 25 feet from the property line.\nFinished Floor Elevation shown on the plan.\n",
    ),
  });
  await page.getByRole("button", { name: "Upload file" }).click();
  await expect(page.getByText("notes.txt", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Process", exact: true }).click();
  await expect(page.getByText("Processing completed")).toBeVisible();

  await page.getByRole("button", { name: "Accept revision" }).click();
  await expect(page.getByText("4 entities", { exact: true })).toBeVisible();

  // One aggregate "text" entity plus one card per extracted key phrase.
  await expect(page.locator(".entity-card", { hasText: "key_phrase" })).toHaveCount(3);
  await expect(page.getByText('"setback"')).toBeVisible();
  await expect(page.getByText('"property line"')).toBeVisible();
  await expect(page.getByText('"finished floor elevation"')).toBeVisible();
});

test("semantic type badges and a plan-sheet snippet are shown for a classified DXF entity", async ({ page }) => {
  const projectName = uniqueName("Phase 9 Semantic and Snippet");

  await page.goto("/");
  await page.getByLabel("New project").fill(projectName);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: "phase9-sample.dxf",
    mimeType: "application/dxf",
    buffer: dxfFixture,
  });
  await page.getByRole("button", { name: "Upload file" }).click();
  await expect(page.getByText("phase9-sample.dxf", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Process", exact: true }).click();
  await expect(page.getByText("Processing completed")).toBeVisible();

  await page.getByRole("button", { name: "Accept revision" }).click();
  await expect(page.getByText("2 entities", { exact: true })).toBeVisible();

  // Semantic-type badges: DXF layer names classify each line entity.
  const parcelCard = page.locator(".entity-card", { hasText: "parcel boundary" });
  await expect(parcelCard).toBeVisible();
  await expect(page.locator(".entity-card", { hasText: "building footprint" })).toBeVisible();

  // Plan-sheet snippet: selecting a DXF-sourced entity and requesting a
  // snippet renders the highlighted source drawing as an inline image.
  await parcelCard.click();
  await page.getByRole("button", { name: "View plan-sheet snippet" }).click();

  const snippetImage = page.locator("img.plan-snippet-image");
  await expect(snippetImage).toBeVisible();
  await expect(snippetImage).toHaveAttribute("src", /^blob:/);
});
