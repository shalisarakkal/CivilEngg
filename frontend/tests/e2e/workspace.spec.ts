import { test, expect, Page, Route } from "@playwright/test";

const API = "http://localhost:8000";

const PROJECT = {
  id: "11111111-1111-1111-1111-111111111111",
  client_id: null,
  name: "Oak Street Site",
  description: null,
  default_unit_system: "imperial",
  coordinate_reference_system: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  archived_at: null,
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/** Wires up the baseline set of API routes every workspace load depends on. */
async function mockBaseline(page: Page, projects: unknown[] = []) {
  await page.route(`${API}/projects`, async (route) => {
    if (route.request().method() === "GET") return json(route, projects);
    return route.continue();
  });
  await page.route(`${API}/admin/files/archived`, (route) => json(route, []));
  await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
    if (route.request().method() === "GET") return json(route, []);
    return route.continue();
  });
  await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions`, (route) => json(route, []));
  await page.route(`${API}/projects/${PROJECT.id}/calculations`, async (route) => {
    if (route.request().method() === "GET") return json(route, []);
    return route.continue();
  });
  await page.route(`${API}/projects/${PROJECT.id}/processing`, (route) => json(route, []));
}

test.describe("project workspace", () => {
  test("upload state: a selected file uploads and appears with its queued status", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() === "POST") {
        return json(
          route,
          {
            id: "file-1",
            project_id: PROJECT.id,
            original_name: "survey.csv",
            media_type: "text/csv",
            size_bytes: 20,
            checksum: "a".repeat(64),
            status: "queued",
            uploaded_at: "2026-01-01T00:00:00Z",
            processed_at: null,
            error_message: null,
            deleted_at: null,
          },
          201,
        );
      }
      return json(route, [
        {
          id: "file-1",
          project_id: PROJECT.id,
          original_name: "survey.csv",
          media_type: "text/csv",
          size_bytes: 20,
          checksum: "a".repeat(64),
          status: "queued",
          uploaded_at: "2026-01-01T00:00:00Z",
          processed_at: null,
          error_message: null,
          deleted_at: null,
        },
      ]);
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: "survey.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("x,y\n0,0\n3,4\n"),
    });
    await page.getByRole("button", { name: "Upload file" }).click();

    await expect(page.getByText("File uploaded and queued for processing.")).toBeVisible();
    await expect(page.getByText("survey.csv")).toBeVisible();
    await expect(page.getByText("Ready to process")).toBeVisible();
  });

  test("calculation state: running a calculation renders its result", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/calculations`, async (route) => {
      if (route.request().method() === "POST") {
        return json(
          route,
          {
            id: "calc-1",
            project_id: PROJECT.id,
            revision_id: null,
            calculation_type: "slope",
            input_entity_ids: null,
            inputs: { start_elevation: 100, end_elevation: 104, horizontal_distance: 100 },
            formula: "(change in elevation / horizontal distance) * 100",
            result: 4,
            unit: "percent",
            assumptions: ["Distance input is measured in ft"],
            details: null,
            created_at: "2026-01-01T00:00:00Z",
          },
          201,
        );
      }
      return json(route, []);
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.getByRole("button", { name: "Run calculation" }).click();

    await expect(page.getByText("slope calculation completed.")).toBeVisible();
    await expect(page.getByText("4.000 percent")).toBeVisible();
  });

  test("error state: a failed project creation shows a message and re-enables the form", async ({ page }) => {
    await mockBaseline(page, []);
    await page.route(`${API}/projects`, async (route) => {
      if (route.request().method() === "POST") return route.abort("failed");
      return json(route, []);
    });

    await page.goto("/");
    await expect(page.getByText("Create your first project.")).toBeVisible();

    const nameInput = page.getByLabel("New project");
    const createButton = page.getByRole("button", { name: "Create project" });
    await nameInput.fill("Broken Site");
    await createButton.click();

    await expect(page.getByText(/request failed/i)).toBeVisible();
    // The form must not be left permanently disabled by the failed request.
    await expect(createButton).toBeEnabled();
    await expect(nameInput).toBeEnabled();

    // Confirm the workspace still works after the transient failure clears.
    await page.unroute(`${API}/projects`);
    await page.route(`${API}/projects`, async (route) => {
      if (route.request().method() === "POST") return json(route, PROJECT, 201);
      return json(route, [PROJECT]);
    });
    await nameInput.fill("Oak Street Site");
    await createButton.click();
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();
  });

  test("error state: an unsupported file upload shows the server's error detail", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() === "POST") {
        return json(route, { detail: "Unsupported file type" }, 400);
      }
      return json(route, []);
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: "plan.exe",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("not supported"),
    });
    const uploadButton = page.getByRole("button", { name: "Upload file" });
    await uploadButton.click();

    await expect(page.getByText("Unsupported file type")).toBeVisible();
    await expect(uploadButton).toBeEnabled();
  });
});
