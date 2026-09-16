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

    await expect(page.getByText("survey.csv uploaded and queued for processing.")).toBeVisible();
    await expect(page.getByText("survey.csv", { exact: true })).toBeVisible();
    await expect(page.locator(".file-status").getByText("Ready to process")).toBeVisible();
  });

  test("upload state: canceling a staged selection clears it without uploading", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    let postCount = 0;
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() === "POST") {
        postCount += 1;
        return route.abort("failed");
      }
      return json(route, []);
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: "survey.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("x,y\n0,0\n"),
    });
    await expect(page.getByText("survey.csv selected for upload.")).toBeVisible();
    await expect(page.getByText("1 file selected")).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).click();

    await expect(page.getByText("1 file cleared. Nothing was uploaded.")).toBeVisible();
    await expect(page.getByText("Choose source file(s)")).toBeVisible();
    await expect(page.getByRole("button", { name: "Upload file" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Cancel" })).toHaveCount(0);
    expect(postCount).toBe(0);
  });

  test("upload state: selecting multiple files uploads all of them and reports the count", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    const uploaded: string[] = [];
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() === "POST") {
        uploaded.push("x");
        return json(
          route,
          {
            id: `file-${uploaded.length}`,
            project_id: PROJECT.id,
            original_name: `survey-${uploaded.length}.csv`,
            media_type: "text/csv",
            size_bytes: 20,
            checksum: `${"a".repeat(63)}${uploaded.length}`,
            status: "queued",
            uploaded_at: "2026-01-01T00:00:00Z",
            processed_at: null,
            error_message: null,
            deleted_at: null,
            document_group_id: `file-${uploaded.length}`,
            superseded_by_id: null,
          },
          201,
        );
      }
      return json(
        route,
        uploaded.map((_, index) => ({
          id: `file-${index + 1}`,
          project_id: PROJECT.id,
          original_name: `survey-${index + 1}.csv`,
          media_type: "text/csv",
          size_bytes: 20,
          checksum: `${"a".repeat(63)}${index + 1}`,
          status: "queued",
          uploaded_at: "2026-01-01T00:00:00Z",
          processed_at: null,
          error_message: null,
          deleted_at: null,
          document_group_id: `file-${index + 1}`,
          superseded_by_id: null,
        })),
      );
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles([
      { name: "survey-1.csv", mimeType: "text/csv", buffer: Buffer.from("x,y\n0,0\n") },
      { name: "survey-2.csv", mimeType: "text/csv", buffer: Buffer.from("x,y\n1,1\n") },
    ]);
    await page.getByRole("button", { name: "Upload files" }).click();

    await expect(page.getByText("2 file(s) uploaded and queued for processing.")).toBeVisible();
    await expect(page.getByText("survey-1.csv")).toBeVisible();
    await expect(page.getByText("survey-2.csv")).toBeVisible();
  });

  test("upload state: dropping a mix of supported and unsupported files stages the supported one with a details breakdown", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() === "POST") {
        return json(
          route,
          {
            id: "file-1",
            project_id: PROJECT.id,
            original_name: "good.csv",
            media_type: "text/csv",
            size_bytes: 20,
            checksum: "a".repeat(64),
            status: "queued",
            uploaded_at: "2026-01-01T00:00:00Z",
            processed_at: null,
            error_message: null,
            deleted_at: null,
            document_group_id: "file-1",
            superseded_by_id: null,
          },
          201,
        );
      }
      return json(route, [
        {
          id: "file-1",
          project_id: PROJECT.id,
          original_name: "good.csv",
          media_type: "text/csv",
          size_bytes: 20,
          checksum: "a".repeat(64),
          status: "queued",
          uploaded_at: "2026-01-01T00:00:00Z",
          processed_at: null,
          error_message: null,
          deleted_at: null,
          document_group_id: "file-1",
          superseded_by_id: null,
        },
      ]);
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    // Drag-and-drop bypasses the file input, so simulate the browser's drop
    // event directly on the upload panel with a mix of an allowed and a
    // disallowed extension.
    await page.evaluate(() => {
      const panel = document.querySelector(".upload-panel");
      if (!panel) throw new Error("upload panel not found");
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File(["x,y\n0,0\n"], "good.csv", { type: "text/csv" }));
      dataTransfer.items.add(new File(["bad"], "bad.exe", { type: "application/octet-stream" }));
      panel.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer }));
    });

    // Dropping only stages the supported file; nothing is uploaded yet.
    await expect(page.getByText("1 file(s) selected for upload, 1 rejected (unsupported type).")).toBeVisible();
    await expect(page.getByText("1 file selected")).toBeVisible();
    await page.getByRole("button", { name: "Show details" }).click();
    await expect(page.locator(".batch-details-group", { hasText: "Selected for upload" })).toContainText("good.csv");
    await expect(page.locator(".batch-details-group", { hasText: "Not supported" })).toContainText(/bad\.exe.*Unsupported file type/);

    await page.getByRole("button", { name: "Upload file" }).click();
    await expect(page.getByText("good.csv uploaded and queued for processing.")).toBeVisible();
  });

  test("batch actions: selecting files in the list shows a batch toolbar that archives them together", async ({ page }) => {
    const filesById: Record<string, unknown> = {
      "file-1": {
        id: "file-1",
        project_id: PROJECT.id,
        original_name: "survey-1.csv",
        media_type: "text/csv",
        size_bytes: 20,
        checksum: "a".repeat(64),
        status: "queued",
        uploaded_at: "2026-01-01T00:00:00Z",
        processed_at: null,
        error_message: null,
        deleted_at: null,
        document_group_id: "file-1",
        superseded_by_id: null,
      },
      "file-2": {
        id: "file-2",
        project_id: PROJECT.id,
        original_name: "survey-2.csv",
        media_type: "text/csv",
        size_bytes: 20,
        checksum: "b".repeat(64),
        status: "queued",
        uploaded_at: "2026-01-02T00:00:00Z",
        processed_at: null,
        error_message: null,
        deleted_at: null,
        document_group_id: "file-2",
        superseded_by_id: null,
      },
    };
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() === "GET") return json(route, Object.values(filesById));
      return route.continue();
    });
    await page.route(`${API}/projects/${PROJECT.id}/files/file-1`, async (route) => {
      if (route.request().method() === "DELETE") {
        delete filesById["file-1"];
        return route.fulfill({ status: 204 });
      }
      return route.continue();
    });
    await page.route(`${API}/projects/${PROJECT.id}/files/file-2`, async (route) => {
      if (route.request().method() === "DELETE") {
        return json(route, { detail: "File is already archived" }, 409);
      }
      return route.continue();
    });

    await page.goto("/");
    await expect(page.getByText("survey-1.csv")).toBeVisible();
    await expect(page.getByText("survey-2.csv")).toBeVisible();

    const rows = page.locator(".file-row");
    await rows.nth(0).locator('input[type="checkbox"]').check();
    await rows.nth(1).locator('input[type="checkbox"]').check();
    await expect(page.getByText("2 selected")).toBeVisible();

    await page.getByRole("button", { name: "Archive selected" }).click();
    await page.getByRole("button", { name: "Archive files" }).click();

    await expect(page.getByText("1 of 2 file(s) archived, 1 failed.")).toBeVisible();
    await expect(page.getByText("survey-1.csv", { exact: true })).not.toBeVisible();
    await expect(page.getByText("survey-2.csv", { exact: true })).toBeVisible();

    // The short summary hides the per-file breakdown behind a "Show details" toggle.
    await expect(page.locator(".batch-details")).toHaveCount(0);
    await page.getByRole("button", { name: "Show details" }).click();
    await expect(page.locator(".batch-details-group", { hasText: "Successful" })).toContainText("survey-1.csv");
    await expect(page.locator(".batch-details-group", { hasText: "Failed" })).toContainText("survey-2.csv — File is already archived");
  });

  test("batch actions: an unexpected error refreshing after a batch still re-enables the toolbar", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    let getFilesCalls = 0;
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      getFilesCalls += 1;
      if (getFilesCalls === 1) {
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
            document_group_id: "file-1",
            superseded_by_id: null,
          },
        ]);
      }
      // Simulate an unexpected failure refreshing project data after the
      // batch's own requests complete -- a 200 with a body that isn't
      // actually valid JSON, so loadProjectData throws parsing it.
      return route.fulfill({ status: 200, contentType: "application/json", body: "not valid json" });
    });
    await page.route(`${API}/projects/${PROJECT.id}/files/file-1/process`, (route) => json(route, { id: "job-1", status: "processing" }, 201));

    await page.goto("/");
    await expect(page.getByText("survey.csv")).toBeVisible();

    await page.locator(".file-row").locator('input[type="checkbox"]').check();
    await page.getByRole("button", { name: "Process selected" }).click();

    await expect(page.getByText("Batch processing failed:")).toBeVisible();
    // The selection (and with it the toolbar) is cleared by the same
    // finally block that resets batchBusy -- if that guard were missing,
    // the toolbar would still be showing here, permanently disabled.
    await expect(page.getByRole("button", { name: "Process selected" })).toHaveCount(0);

    // Re-selecting proves batchBusy itself was actually reset, not just the
    // selection: the button comes back enabled, not stuck mid-batch.
    await page.locator(".file-row").locator('input[type="checkbox"]').check();
    await expect(page.getByRole("button", { name: "Process selected" })).toBeEnabled();
  });

  test("batch actions: accepting selected files skips ones that are already accepted or not completed", async ({ page }) => {
    const files = [
      {
        id: "file-1",
        project_id: PROJECT.id,
        original_name: "ready.csv",
        media_type: "text/csv",
        size_bytes: 20,
        checksum: "a".repeat(64),
        status: "completed",
        uploaded_at: "2026-01-01T00:00:00Z",
        processed_at: "2026-01-01T00:05:00Z",
        error_message: null,
        deleted_at: null,
        document_group_id: "file-1",
        superseded_by_id: null,
      },
      {
        id: "file-2",
        project_id: PROJECT.id,
        original_name: "still-queued.csv",
        media_type: "text/csv",
        size_bytes: 20,
        checksum: "b".repeat(64),
        status: "queued",
        uploaded_at: "2026-01-02T00:00:00Z",
        processed_at: null,
        error_message: null,
        deleted_at: null,
        document_group_id: "file-2",
        superseded_by_id: null,
      },
      {
        id: "file-3",
        project_id: PROJECT.id,
        original_name: "already-accepted.csv",
        media_type: "text/csv",
        size_bytes: 20,
        checksum: "c".repeat(64),
        status: "completed",
        uploaded_at: "2026-01-03T00:00:00Z",
        processed_at: "2026-01-03T00:05:00Z",
        error_message: null,
        deleted_at: null,
        document_group_id: "file-3",
        superseded_by_id: null,
      },
    ];
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() === "GET") return json(route, files);
      return route.continue();
    });
    await page.route(`${API}/projects/${PROJECT.id}/processing`, (route) =>
      json(route, [{ id: "job-3", project_id: PROJECT.id, source_file_id: "file-3", status: "completed", parser_name: "csv", started_at: null, completed_at: null, warnings: null, error_message: null }]),
    );
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions`, (route) =>
      json(route, [{ id: "rev-3", revision_number: 1, created_at: "2026-01-03T00:06:00Z", source_job_ids: ["job-3"], notes: null }]),
    );
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions/rev-3/entities*`, (route) => json(route, []));

    let file1AcceptCalls = 0;
    let file2AcceptCalls = 0;
    let file3AcceptCalls = 0;
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions/from-extraction/file-1`, (route) => {
      file1AcceptCalls += 1;
      return json(route, { id: "rev-1", revision_number: 2, created_at: "2026-01-04T00:00:00Z", source_job_ids: ["job-1"], notes: null }, 201);
    });
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions/from-extraction/file-2`, (route) => {
      file2AcceptCalls += 1;
      return json(route, { detail: "should never be called" }, 500);
    });
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions/from-extraction/file-3`, (route) => {
      file3AcceptCalls += 1;
      return json(route, { detail: "should never be called" }, 500);
    });

    await page.goto("/");
    await expect(page.getByText("ready.csv")).toBeVisible();

    const rows = page.locator(".file-row");
    await rows.nth(0).locator('input[type="checkbox"]').check();
    await rows.nth(1).locator('input[type="checkbox"]').check();
    await rows.nth(2).locator('input[type="checkbox"]').check();
    await expect(page.getByText("3 selected")).toBeVisible();

    await page.getByRole("button", { name: "Accept selected" }).click();

    await expect(page.getByText("3 file(s): 1 accepted, 2 skipped.")).toBeVisible();
    await page.getByRole("button", { name: "Show details" }).click();
    await expect(page.locator(".batch-details-group", { hasText: /^Accepted/ })).toContainText("ready.csv");
    await expect(page.locator(".batch-details-group", { hasText: /^Skipped/ })).toContainText("still-queued.csv — File is not completed (status: queued)");
    await expect(page.locator(".batch-details-group", { hasText: /^Skipped/ })).toContainText("already-accepted.csv — Revision already accepted");

    // The two ineligible files must never have been sent to the server at all.
    expect(file2AcceptCalls).toBe(0);
    expect(file3AcceptCalls).toBe(0);
    expect(file1AcceptCalls).toBe(1);

    // The newly-accepted file's own row reflects it, same as a single accept would.
    await expect(rows.filter({ hasText: "ready.csv" }).getByRole("button", { name: "Revision accepted" })).toBeVisible();
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
    // An unsupported-type rejection would only fail the same way again, so the
    // picker resets instead of leaving the file selected for a pointless retry.
    await expect(page.getByText("Choose source file(s)")).toBeVisible();
    await expect(uploadButton).toBeDisabled();
  });

  test("error state: a transient upload failure keeps the file selected for retry", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() === "POST") {
        return json(route, { detail: "Internal Server Error" }, 500);
      }
      return json(route, []);
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: "survey.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("x,y\n0,0\n"),
    });
    const uploadButton = page.getByRole("button", { name: "Upload file" });
    await uploadButton.click();

    await expect(page.getByText("survey.csv could not be uploaded and queued for processing")).toBeVisible();
    // Unlike a duplicate or unsupported-type rejection, a server error might
    // succeed on retry, so the file stays selected.
    await expect(page.getByText("1 file selected")).toBeVisible();
    await expect(uploadButton).toBeEnabled();
  });
});
