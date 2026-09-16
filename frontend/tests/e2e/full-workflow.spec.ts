import { test, expect } from "@playwright/test";

/**
 * Exercises the primary workflow against the real backend and a real
 * (SQLite, file-backed) database and storage directory, unlike
 * workspace.spec.ts which mocks the API. Each test uses a unique project
 * name since the database persists across local runs.
 */

function uniqueName(label: string): string {
  return `${label} ${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

test("create project, upload, process, inspect, calculate, and ask", async ({ page }) => {
  const projectName = uniqueName("E2E Workflow Site");

  await page.goto("/");

  // Create a project.
  await page.getByLabel("New project").fill(projectName);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  // Upload a supported file.
  await page.locator('input[type="file"]').setInputFiles({
    name: "points.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("x,y\n0,0\n3,4\n"),
  });
  await page.getByRole("button", { name: "Upload file" }).click();
  await expect(page.getByText("points.csv", { exact: true })).toBeVisible();
  await expect(page.locator(".file-status").getByText("Ready to process")).toBeVisible();

  // Process it and observe the status transition.
  await page.getByRole("button", { name: "Process", exact: true }).click();
  await expect(page.getByText("Processing completed")).toBeVisible();

  // Accept the revision into the site model.
  await page.getByRole("button", { name: "Accept revision" }).click();
  await expect(page.getByText("2 entities", { exact: true })).toBeVisible();

  // Inspect: the extracted points render as entity cards.
  const entityCards = page.locator(".entity-card");
  await expect(entityCards).toHaveCount(2);
  await expect(entityCards.first()).toContainText("point");

  // Calculate: Distance is the default geometry that matches the two
  // uploaded points, so running it with defaults produces a known result.
  await page.getByLabel("Calculation").selectOption("distance");
  await page.getByRole("button", { name: "Run calculation" }).click();
  await expect(page.getByText("distance calculation completed.")).toBeVisible();
  await expect(page.getByText("5.000 ft")).toBeVisible();

  // Selecting the result highlights the source geometry it was computed from.
  await page.getByRole("button", { name: /^distance/ }).click();
  await expect(page.getByText(/Highlighting source geometry from points\.csv/)).toBeVisible();

  // Ask: a geometry-backed question is answered deterministically, not invented.
  await page.getByPlaceholder("What is the setback distance?").fill("What is the setback distance?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByText("Question answered.")).toBeVisible();
  // The Q&A path computes independently of the manual calculation form's
  // chosen units and always reports in meters (see ai_service._answer_distance).
  await expect(page.getByText("The measured distance is 5.000 m.")).toBeVisible();
  await expect(page.getByText(/deterministic geometry calculation/i)).toBeVisible();

  // Site summary is also available from the same accepted revision.
  await page.getByRole("button", { name: "Request site summary" }).click();
  await expect(page.getByText("Site summary generated.")).toBeVisible();
  await expect(page.getByText("Site model contains 2 extracted entities.")).toBeVisible();
});

test("batch-accepting revisions for multiple files creates one distinct revision per file", async ({ page }) => {
  const projectName = uniqueName("E2E Batch Accept Site");

  await page.goto("/");
  await page.getByLabel("New project").fill(projectName);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles([
    { name: "batch-a.csv", mimeType: "text/csv", buffer: Buffer.from("x,y\n0,0\n1,1\n") },
    { name: "batch-b.csv", mimeType: "text/csv", buffer: Buffer.from("x,y\n2,2\n3,3\n") },
    { name: "batch-c.csv", mimeType: "text/csv", buffer: Buffer.from("x,y\n4,4\n5,5\n") },
  ]);
  await page.getByRole("button", { name: "Upload files" }).click();
  await expect(page.getByText("3 file(s) uploaded and queued for processing.")).toBeVisible();

  await page.locator(".list-heading .select-all input").check();
  await page.getByRole("button", { name: "Process selected" }).click();
  await expect(page.getByText("3 file(s) processed.")).toBeVisible();

  await page.locator(".list-heading .select-all input").check();
  await page.getByRole("button", { name: "Accept selected" }).click();

  // No skips and nothing already accepted, so this is the plain (pre-skip)
  // wording path in summarizeBatchResult, not the "N file(s): ..." one.
  await expect(page.getByText("3 file(s) accepted.")).toBeVisible();

  // Every row independently reflects the accept, same as three individual
  // "Accept revision" clicks would -- proving the sequential batch produced
  // three distinct revisions rather than colliding on the same one.
  const acceptedButtons = page.getByRole("button", { name: "Revision accepted" });
  await expect(acceptedButtons).toHaveCount(3);

  // Three distinct, sequentially-numbered revisions -- not two accepts
  // colliding on the same revision_number, the historical bug this
  // sequential (not parallel) batch implementation exists to avoid.
  const revisionOptions = page.locator(".revision-selector select option");
  await expect(revisionOptions).toHaveCount(3);
  const optionTexts = await revisionOptions.allTextContents();
  expect(optionTexts.some((text) => text.includes("Revision 1 ·"))).toBe(true);
  expect(optionTexts.some((text) => text.includes("Revision 2 ·"))).toBe(true);
  expect(optionTexts.some((text) => text.includes("Revision 3 ·"))).toBe(true);
});

test("asking a question with no accepted revision refuses to invent an answer", async ({ page }) => {
  const projectName = uniqueName("E2E No-Data Site");

  await page.goto("/");
  await page.getByLabel("New project").fill(projectName);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  await page.getByPlaceholder("What is the setback distance?").fill("What is the setback distance?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  await expect(page.getByText("Question answered.")).toBeVisible();
  await expect(page.getByText("Insufficient data to answer this question.")).toBeVisible();
});
