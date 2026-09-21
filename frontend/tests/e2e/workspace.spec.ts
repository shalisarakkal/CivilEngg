import { test, expect, Page, Route } from "@playwright/test";

const API = "http://localhost:8000";

const MOCK_CURRENT_USER = {
  id: "99999999-9999-9999-9999-999999999999",
  username: "mock-power-user",
  role: "power_user",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  disabled_at: null,
};

const PROJECT = {
  id: "11111111-1111-1111-1111-111111111111",
  client_id: null,
  // Owned by MOCK_CURRENT_USER: several tests exercise owner-only actions
  // (Archive project, Reassign owner, Add collaborator), which are now
  // gated client-side on currentUser.id === project.owner_id.
  owner_id: MOCK_CURRENT_USER.id,
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
async function mockBaseline(page: Page, projects: { id: string }[] = []) {
  // AuthProvider calls this before rendering anything else -- without a
  // mock it would fall through to the real backend (a real webServer is
  // running per playwright.config.ts, but with no session cookie this
  // page's own fetch would 401 and redirect to /login before any of the
  // routes below ever mattered), so every other mock in this file only
  // matters once this one exists.
  await page.route(`${API}/auth/me`, (route) => json(route, MOCK_CURRENT_USER));
  await page.route(`${API}/projects`, async (route) => {
    if (route.request().method() === "GET") return json(route, projects);
    return route.continue();
  });
  await page.route(`${API}/admin/files/archived`, (route) => json(route, []));
  for (const project of projects) {
    await page.route(`${API}/projects/${project.id}/files`, async (route) => {
      if (route.request().method() === "GET") return json(route, []);
      return route.continue();
    });
    await page.route(`${API}/projects/${project.id}/site-model/revisions`, (route) => json(route, []));
    await page.route(`${API}/projects/${project.id}/calculations`, async (route) => {
      if (route.request().method() === "GET") return json(route, []);
      return route.continue();
    });
    await page.route(`${API}/projects/${project.id}/processing`, (route) => json(route, []));
  }
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

  test("activity log: an earlier action's outcome is still recoverable after a later one overwrites the status line (Phase 12)", async ({ page }) => {
    // Reproduces the real reported bug this phase fixes: the status line
    // covers only the single most recent action, so running a calculation
    // and then requesting a summary used to leave no trace anywhere in the
    // DOM that the calculation had happened at all -- checking back later,
    // there was no way to recover it.
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions`, (route) =>
      json(route, [{ id: "rev-1", revision_number: 1, created_at: "2026-01-01T00:00:00Z", source_job_ids: ["job-1"], notes: null }]),
    );
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions/rev-1/entities*`, (route) => json(route, []));
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
    await page.route(`${API}/projects/${PROJECT.id}/summaries`, async (route) => {
      if (route.request().method() === "GET") return json(route, []);
      return json(route, {
        id: "summary-1",
        project_id: PROJECT.id,
        revision_ids: null,
        content: {
          summary: "Flat, single-parcel site.",
          grading: "Flat site.",
          drainage: "No issues noted.",
          utilities: "None mapped.",
          attention_flags: [],
          limitations: ["Deterministic summary; not a substitute for a licensed review."],
        },
        created_at: "2026-01-01T00:00:00Z",
      });
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.getByRole("button", { name: "Run calculation" }).click();
    await expect(page.getByText("slope calculation completed.")).toBeVisible();

    await page.getByRole("button", { name: "Request site summary" }).click();
    await expect(page.getByText("Site summary generated.")).toBeVisible();
    // The status line now shows only the summary outcome -- the calculation
    // message is no longer the visible banner (matches pre-Phase-12 behavior;
    // the fix is that it's still recoverable, checked below, not that the
    // banner itself stops being single-line).
    await expect(page.locator(".message")).not.toContainText("slope calculation completed.");

    await page.getByRole("button", { name: /^Activity log/ }).click();
    const log = page.locator(".activity-log");
    await expect(log).toContainText("slope calculation completed.");
    await expect(log).toContainText("Site summary generated.");
    // Each entry names who performed it, not just what and when.
    await expect(log.locator(".activity-log-user").first()).toHaveText(MOCK_CURRENT_USER.username);
  });

  test("site intelligence: generating multiple summaries keeps a history instead of replacing", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions`, (route) =>
      json(route, [{ id: "rev-1", revision_number: 1, created_at: "2026-01-01T00:00:00Z", source_job_ids: ["job-1"], notes: null }]),
    );
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions/rev-1/entities*`, (route) => json(route, []));
    let callCount = 0;
    await page.route(`${API}/projects/${PROJECT.id}/summaries`, async (route) => {
      if (route.request().method() === "GET") return json(route, []);
      callCount += 1;
      return json(route, {
        id: `summary-${callCount}`,
        project_id: PROJECT.id,
        revision_ids: null,
        content: {
          summary: `Summary number ${callCount}.`,
          grading: "Flat site.",
          drainage: "No issues noted.",
          utilities: "None mapped.",
          attention_flags: [],
          limitations: ["Deterministic summary; not a substitute for a licensed review."],
        },
        created_at: `2026-01-0${callCount}T00:00:00Z`,
      });
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.getByRole("button", { name: "Request site summary" }).click();
    await expect(page.getByText("Summary number 1.")).toBeVisible();

    await page.getByRole("button", { name: "Request site summary" }).click();
    await expect(page.getByText("Summary number 2.")).toBeVisible();
    // The first summary must still be visible -- not replaced by the second.
    await expect(page.getByText("Summary number 1.")).toBeVisible();

    const cards = page.locator(".summary-card");
    await expect(cards).toHaveCount(2);
    // Most recent first.
    await expect(cards.nth(0)).toContainText("Summary number 2.");
    await expect(cards.nth(1)).toContainText("Summary number 1.");
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

  test("empty state: archiving the active project selects the last remaining one, or prompts to choose among several", async ({ page }) => {
    const PROJECT_B = { ...PROJECT, id: "22222222-2222-2222-2222-222222222222", name: "Maple Ave Site" };
    const PROJECT_C = { ...PROJECT, id: "33333333-3333-3333-3333-333333333333", name: "Elm Street Site" };
    await mockBaseline(page, [PROJECT, PROJECT_B, PROJECT_C]);
    await page.route(`${API}/admin/projects/archived`, (route) => json(route, []));
    await page.route(`${API}/projects/${PROJECT.id}/archive`, (route) => json(route, { ...PROJECT, archived_at: "2026-01-01T00:00:00Z" }));
    await page.route(`${API}/projects/${PROJECT_B.id}/archive`, (route) => json(route, { ...PROJECT_B, archived_at: "2026-01-01T00:00:00Z" }));

    await page.goto("/");
    // The initial load selects the first project returned by the API.
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    // Archiving the active project with two others left should not drop to
    // the empty state -- it's ambiguous which of the two remaining projects
    // to show, so the user is prompted to choose instead.
    await page.getByRole("button", { name: "Archive project" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive project" }).click();
    await expect(page.getByText("Select your project.")).toBeVisible();
    await expect(page.getByText("Create your first project.")).toHaveCount(0);

    // Select the second project, then archive it too -- now only one
    // project is left, so there's nothing ambiguous about auto-selecting it.
    await page.locator(".project-list").getByText(PROJECT_B.name).click();
    await expect(page.getByRole("heading", { name: PROJECT_B.name })).toBeVisible();
    await page.getByRole("button", { name: "Archive project" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive project" }).click();

    await expect(page.getByRole("heading", { name: PROJECT_C.name })).toBeVisible();
    await expect(page.getByText("Select your project.")).toHaveCount(0);
  });

  test("project lifecycle: archive, restore, and permanently purge from the UI", async ({ page }) => {
    let archivedProjects: unknown[] = [];
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/admin/projects/archived`, (route) => json(route, archivedProjects));
    await page.route(`${API}/projects/${PROJECT.id}/archive`, (route) => {
      archivedProjects = [
        { ...PROJECT, archived_at: "2026-01-01T00:00:00Z", purge_scheduled_at: "2026-07-01T00:00:00Z", purge_warning: false },
      ];
      return json(route, { ...PROJECT, archived_at: "2026-01-01T00:00:00Z" });
    });
    await page.route(`${API}/admin/projects/${PROJECT.id}/restore`, (route) => {
      archivedProjects = [];
      return json(route, { ...PROJECT, archived_at: null });
    });
    await page.route(`${API}/admin/projects/${PROJECT.id}`, async (route) => {
      if (route.request().method() === "DELETE") {
        archivedProjects = [];
        return route.fulfill({ status: 204 });
      }
      return route.continue();
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    // Archive.
    await page.getByRole("button", { name: "Archive project" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive project" }).click();
    await expect(page.getByText(`${PROJECT.name} was archived.`)).toBeVisible();
    await expect(page.getByText("Create your first project.")).toBeVisible();
    await expect(page.getByText("1 archived project")).toBeVisible();
    await expect(page.locator(".admin-panel", { hasText: "Archived projects" })).toContainText(PROJECT.name);

    // Restore.
    await page.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByText(`${PROJECT.name} was restored.`)).toBeVisible();
    await expect(page.getByText("0 archived projects")).toBeVisible();
    await expect(page.locator(".project-list")).toContainText(PROJECT.name);
    // Restoring doesn't re-select it -- the same "which one?" ambiguity as
    // archiving applies here too, so it just reappears in the list.
    await expect(page.getByText("Select your project.")).toBeVisible();

    // Re-select it, archive it again, then permanently purge it.
    await page.locator(".project-list").getByText(PROJECT.name).click();
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();
    await page.getByRole("button", { name: "Archive project" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive project" }).click();
    await expect(page.getByText("1 archived project")).toBeVisible();

    await page.getByRole("button", { name: "Purge" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Permanently delete" }).click();
    await expect(page.getByText(`${PROJECT.name} was permanently deleted.`)).toBeVisible();
    await expect(page.getByText("0 archived projects")).toBeVisible();
  });

  test("archived panels show an auto-purge countdown, flagged once within the warning window", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/admin/projects/archived`, (route) =>
      json(route, [
        {
          ...PROJECT,
          name: "Plenty Of Time Site",
          id: "aaaaaaaa-1111-1111-1111-111111111111",
          archived_at: "2026-01-01T00:00:00Z",
          purge_scheduled_at: new Date(Date.now() + 90 * 24 * 60 * 60 * 1000).toISOString(),
          purge_warning: false,
        },
      ]),
    );
    await page.route(`${API}/admin/files/archived`, (route) =>
      json(route, [
        {
          id: "file-1",
          project_id: PROJECT.id,
          original_name: "almost-gone.csv",
          media_type: "text/csv",
          size_bytes: 20,
          checksum: "a".repeat(64),
          status: "completed",
          uploaded_at: "2026-01-01T00:00:00Z",
          processed_at: null,
          error_message: null,
          deleted_at: "2026-01-01T00:00:00Z",
          document_group_id: "file-1",
          superseded_by_id: null,
          purge_scheduled_at: new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString(),
          purge_warning: true,
        },
      ]),
    );

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    // Plenty of time left: shown, but not flagged as a warning.
    const projectRow = page.locator(".archive-row", { hasText: "Plenty Of Time Site" });
    await expect(projectRow).toContainText("Auto-deletes in 90 days");
    await expect(projectRow.locator(".purge-countdown-warning")).toHaveCount(0);

    // Within the warning window: same countdown style, flagged.
    const fileRow = page.locator(".archive-row", { hasText: "almost-gone.csv" });
    await expect(fileRow).toContainText("Auto-deletes in 5 days");
    await expect(fileRow.locator(".purge-countdown-warning")).toHaveCount(1);
  });

  test("site intelligence: switching projects clears a selected revision-scope filter", async ({ page }) => {
    // Regression test: qaRevisionIds (the "Scope" checkboxes limiting a
    // summary/question to specific revisions) was never reset on project
    // switch, so a scope selected in one project was silently sent as-is to a
    // different project's questions/summaries endpoint.
    const PROJECT_B = { ...PROJECT, id: "22222222-2222-2222-2222-222222222222", name: "Maple Ave Site" };
    await mockBaseline(page, [PROJECT, PROJECT_B]);
    const REVISION_A = { id: "rev-a", revision_number: 1, created_at: "2026-01-01T00:00:00Z", source_job_ids: [], notes: null };
    const REVISION_B = { id: "rev-b", revision_number: 1, created_at: "2026-01-01T00:00:00Z", source_job_ids: [], notes: null };
    await page.route(`${API}/projects/${PROJECT.id}/site-model/revisions`, (route) => json(route, [REVISION_A]));
    await page.route(`${API}/projects/${PROJECT_B.id}/site-model/revisions`, (route) => json(route, [REVISION_B]));

    let capturedBody: { question: string; revision_ids: string[] | null } | null = null;
    await page.route(`${API}/projects/${PROJECT_B.id}/questions`, async (route) => {
      capturedBody = route.request().postDataJSON();
      return json(route, {
        id: "q-1",
        project_id: PROJECT_B.id,
        revision_ids: null,
        question: "What is the setback distance?",
        intent: "distance",
        answer: { answer: "Insufficient data to answer this question.", method: "mock", source_references: [], limitations: [], confidence: 0 },
        created_at: "2026-01-01T00:00:00Z",
      });
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    // Select Project A's only revision as the scope.
    await page.locator(".qa-scope-option").getByRole("checkbox").check();
    await expect(page.getByText("Selected revisions only.")).toBeVisible();

    // Switch to Project B, which has a different revision (rev-b), and ask a
    // question without touching the scope controls there.
    await page.locator(".project-list").getByText(PROJECT_B.name).click();
    await expect(page.getByRole("heading", { name: PROJECT_B.name })).toBeVisible();
    await expect(page.getByText("Whole project (every accepted document's latest revision).")).toBeVisible();

    await page.getByPlaceholder("What is the setback distance?").fill("What is the setback distance?");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect.poll(() => capturedBody).not.toBeNull();
    // Must not still be carrying Project A's revision id ("rev-a").
    expect(capturedBody).toEqual({ question: "What is the setback distance?", revision_ids: null });
  });

  test("upload state: the file picker rejects new selections while an upload is in flight", async ({ page }) => {
    // Regression test: nothing prevented staging a new file while a previous
    // upload was in flight, and uploadFiles' finally block then replaced
    // pendingFiles wholesale with its own stale, closed-over result once that
    // upload resolved -- silently wiping out whatever had been staged since.
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/admin/projects/archived`, (route) => json(route, []));
    let releaseUpload: () => void = () => {};
    const uploadGate = new Promise<void>((resolve) => {
      releaseUpload = resolve;
    });
    const uploadedNames: string[] = [];
    await page.route(`${API}/projects/${PROJECT.id}/files`, async (route) => {
      if (route.request().method() !== "POST") return json(route, []);
      const body = route.request().postData() ?? "";
      const isFirstUpload = uploadedNames.length === 0;
      const name = body.includes("b.csv") ? "b.csv" : "a.csv";
      uploadedNames.push(name);
      if (isFirstUpload) await uploadGate;
      return json(
        route,
        {
          id: `file-${name}`,
          project_id: PROJECT.id,
          original_name: name,
          media_type: "text/csv",
          size_bytes: 10,
          checksum: "a".repeat(64),
          status: "queued",
          uploaded_at: "2026-01-01T00:00:00Z",
          processed_at: null,
          error_message: null,
          deleted_at: null,
        },
        201,
      );
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: "a.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("x,y\n0,0\n"),
    });
    await page.getByRole("button", { name: "Upload file" }).click();
    await expect(page.getByRole("button", { name: "Upload file" })).toBeDisabled();

    // While A is still uploading, the picker itself must refuse a new
    // selection rather than silently accept one that will just be dropped.
    await expect(page.locator('input[type="file"]')).toBeDisabled();

    // Let A's upload resolve, and the picker become usable again.
    releaseUpload();
    await expect(page.locator('input[type="file"]')).toBeEnabled();
    await expect(page.locator(".file-picker span")).toHaveText("Choose source file(s)");

    // Staging and uploading B afterward must still work normally.
    await page.locator('input[type="file"]').setInputFiles({
      name: "b.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("x,y\n1,1\n"),
    });
    await expect(page.locator(".file-picker span")).toHaveText("1 file selected");
    await page.getByRole("button", { name: "Upload file" }).click();
    await expect.poll(() => uploadedNames).toEqual(["a.csv", "b.csv"]);
  });

  test("Manage collaborators falls back to a single-username lookup when the caller can't list every user (Power User owner)", async ({
    page,
  }) => {
    // GET /users is admin-only; a Power User project owner (who can also
    // open this modal) gets a 403 there and has no way to browse/multi-select
    // candidates, so falls back to the original one-at-a-time flow instead
    // of an empty, broken list.
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/users`, (route) => json(route, { detail: "Admin role required" }, 403));
    await page.route(`${API}/users/lookup*`, (route) =>
      json(route, { id: "found-user-id", username: "jsmith" }),
    );
    let postBody: unknown = null;
    await page.route(`${API}/projects/${PROJECT.id}/members`, async (route) => {
      if (route.request().method() === "POST") {
        postBody = route.request().postDataJSON();
        return json(route, {}, 201);
      }
      return json(route, []);
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();
    await page.getByRole("button", { name: "Manage collaborators" }).click();

    // GET /users failing means the owner's own name is resolved locally
    // (the caller IS the owner here), not looked up.
    await expect(page.locator(".collaborator-owner-row")).toContainText(MOCK_CURRENT_USER.username);
    await expect(page.locator(".collaborator-candidate-list")).toHaveCount(0);
    const usernameInput = page.locator("#new-collaborator-username");
    await expect(usernameInput).toBeVisible();
    await usernameInput.fill("jsmith");
    await page.getByRole("button", { name: "Add", exact: true }).click();

    await expect(page.getByText("jsmith was added to Oak Street Site.")).toBeVisible();
    expect(postBody).toEqual({ user_id: "found-user-id" });
  });

  test("Manage collaborators lets the owner remove an existing collaborator", async ({ page }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/users`, (route) => json(route, { detail: "Admin role required" }, 403));
    let deleteCalled = false;
    await page.route(`${API}/projects/${PROJECT.id}/members`, (route) =>
      json(route, [
        {
          id: "membership-1",
          project_id: PROJECT.id,
          user_id: "collab-1",
          username: "jsmith",
          role: "user",
          created_at: "2026-01-01T00:00:00Z",
        },
      ]),
    );
    await page.route(`${API}/projects/${PROJECT.id}/members/collab-1`, (route) => {
      deleteCalled = true;
      return route.fulfill({ status: 204 });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "Manage collaborators" }).click();

    await expect(page.getByText("Collaborators (1)")).toBeVisible();
    await page.getByRole("button", { name: "Remove" }).click();

    await expect(page.getByText("jsmith was removed from Oak Street Site.")).toBeVisible();
    expect(deleteCalled).toBe(true);
  });

  test("Manage collaborators reassigns the owner with an explicit confirmation step", async ({
    page,
  }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/users`, (route) => json(route, { detail: "Admin role required" }, 403));
    await page.route(`${API}/projects/${PROJECT.id}/members`, (route) =>
      json(route, [
        {
          id: "membership-1",
          project_id: PROJECT.id,
          user_id: "collab-1",
          username: "pu_jane",
          role: "power_user",
          created_at: "2026-01-01T00:00:00Z",
        },
      ]),
    );
    let patchBody: unknown = null;
    await page.route(`${API}/projects/${PROJECT.id}/owner`, async (route) => {
      patchBody = route.request().postDataJSON();
      return json(route, { ...PROJECT, owner_id: "collab-1" });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "Manage collaborators" }).click();
    await page.getByLabel("Reassign owner to").selectOption("collab-1");

    // Reassignment requires an explicit confirmation, not an immediate
    // change on selecting a candidate.
    await expect(page.getByText("Make pu_jane the new owner of Oak Street Site?")).toBeVisible();
    expect(patchBody).toBeNull();

    await page.getByRole("button", { name: "Confirm reassign" }).click();

    await expect(page.getByText("Oak Street Site's owner was changed to pu_jane.")).toBeVisible();
    expect(patchBody).toEqual({ owner_id: "collab-1" });
  });
});

test.describe("project workspace as admin", () => {
  const MOCK_ADMIN = {
    id: "77777777-7777-7777-7777-777777777777",
    username: "mock-admin",
    role: "admin",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    disabled_at: null,
  };

  test("creating a project requires choosing an owner, since an admin has no project of their own to become owner of", async ({
    page,
  }) => {
    // Reproduces a real reported bug: an admin's "Project could not be
    // created." gave no indication that routes.py's create_project (ADR-009:
    // "a project's owner must be a power_user") requires an explicit
    // owner_id for an admin caller, since -- unlike a power_user -- an
    // admin never auto-becomes the owner of a project they create.
    await mockBaseline(page, []);
    await page.route(`${API}/auth/me`, (route) => json(route, MOCK_ADMIN));
    await page.route(`${API}/admin/projects/archived`, (route) => json(route, []));
    await page.route(`${API}/users`, (route) =>
      json(route, [
        { id: "pu-1", username: "pu_jane", role: "power_user", disabled_at: null },
        { id: "pu-2", username: "pu_disabled", role: "power_user", disabled_at: "2026-01-01T00:00:00Z" },
        { id: "u-1", username: "plain_user", role: "user", disabled_at: null },
      ]),
    );
    let postBody: unknown = null;
    await page.route(`${API}/projects`, async (route) => {
      if (route.request().method() === "POST") {
        postBody = route.request().postDataJSON();
        return json(
          route,
          {
            id: "new-project-id",
            client_id: null,
            owner_id: "pu-1",
            name: "Oak Street Site",
            description: null,
            default_unit_system: "imperial",
            coordinate_reference_system: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
            archived_at: null,
          },
          201,
        );
      }
      return json(route, []);
    });
    await page.route(`${API}/projects/new-project-id/files`, (route) => json(route, []));
    await page.route(`${API}/projects/new-project-id/site-model/revisions`, (route) => json(route, []));
    await page.route(`${API}/projects/new-project-id/calculations`, (route) => json(route, []));
    await page.route(`${API}/projects/new-project-id/processing`, (route) => json(route, []));
    await page.route(`${API}/projects/new-project-id/summaries`, (route) => json(route, []));
    await page.route(`${API}/projects/new-project-id/activity-events`, (route) => json(route, []));

    await page.goto("/");

    // Only the enabled Power User is offered -- not the disabled one, and
    // not the plain "user" account, either of which would fail routes.py's
    // own "A project owner must be a power_user" check.
    const ownerSelect = page.getByLabel("Project owner");
    await expect(ownerSelect.locator("option")).toHaveCount(2); // placeholder + pu_jane
    await expect(ownerSelect.getByText("pu_disabled")).toHaveCount(0);
    await expect(ownerSelect.getByText("plain_user")).toHaveCount(0);

    await page.locator("#project-name").fill("Oak Street Site");
    await page.getByRole("button", { name: "Create project" }).click();

    await expect(page.getByText("Choose an owner (a Power User) for the new project.")).toBeVisible();
    expect(postBody).toBeNull();

    await ownerSelect.selectOption("pu-1");
    await page.getByRole("button", { name: "Create project" }).click();

    await expect(page.getByText("Project created. Add a source file to begin.")).toBeVisible();
    expect(postBody).toEqual({ name: "Oak Street Site", owner_id: "pu-1" });
  });

  test("a real (non-owner-id) error from the server is shown instead of a generic message", async ({
    page,
  }) => {
    // The pre-fix bug: any non-2xx response was reported as the same
    // generic "Project could not be created.", discarding whatever detail
    // the server actually sent -- leaving the user with no way to tell a
    // missing-owner error from a name conflict from anything else.
    await mockBaseline(page, []);
    await page.route(`${API}/auth/me`, (route) => json(route, MOCK_ADMIN));
    await page.route(`${API}/admin/projects/archived`, (route) => json(route, []));
    await page.route(`${API}/users`, (route) =>
      json(route, [{ id: "pu-1", username: "pu_jane", role: "power_user", disabled_at: null }]),
    );
    await page.route(`${API}/projects`, async (route) => {
      if (route.request().method() === "POST") {
        return json(route, { detail: "A project owner must belong to the project's own tenant" }, 422);
      }
      return json(route, []);
    });

    await page.goto("/");
    await page.locator("#project-name").fill("Oak Street Site");
    await page.getByLabel("Project owner").selectOption("pu-1");
    await page.getByRole("button", { name: "Create project" }).click();

    await expect(
      page.getByText("A project owner must belong to the project's own tenant"),
    ).toBeVisible();
  });

  test("Manage collaborators supports multi-select, adding several collaborators in one go", async ({
    page,
  }) => {
    await mockBaseline(page, [PROJECT]);
    await page.route(`${API}/auth/me`, (route) => json(route, MOCK_ADMIN));
    await page.route(`${API}/admin/projects/archived`, (route) => json(route, []));
    await page.route(`${API}/users`, (route) =>
      json(route, [
        // Already the owner -- must not appear as a candidate.
        { id: PROJECT.owner_id, username: "owner_user", role: "power_user", disabled_at: null },
        // Already a member -- must not appear as a candidate either.
        { id: "existing-member", username: "existing_member", role: "user", disabled_at: null },
        { id: "u-1", username: "jsmith", role: "user", disabled_at: null },
        { id: "pu-1", username: "pu_jane", role: "power_user", disabled_at: null },
        { id: "disabled-1", username: "disabled_user", role: "user", disabled_at: "2026-01-01T00:00:00Z" },
        { id: "admin-1", username: "another_admin", role: "admin", disabled_at: null },
      ]),
    );
    const postedUserIds: string[] = [];
    await page.route(`${API}/projects/${PROJECT.id}/members`, async (route) => {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON() as { user_id: string };
        postedUserIds.push(body.user_id);
        return json(route, {}, 201);
      }
      return json(route, [
        {
          id: "membership-1",
          project_id: PROJECT.id,
          user_id: "existing-member",
          username: "existing_member",
          role: "user",
          created_at: "2026-01-01T00:00:00Z",
        },
      ]);
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: PROJECT.name })).toBeVisible();
    await page.getByRole("button", { name: "Manage collaborators" }).click();

    // The owner's name is resolved from GET /users since the admin caller
    // isn't the owner themselves.
    await expect(page.locator(".collaborator-owner-row")).toContainText("owner_user");
    await expect(page.getByText("Collaborators (1)")).toBeVisible();
    await expect(page.locator(".existing-collaborator-list")).toContainText("existing_member");

    const list = page.locator(".collaborator-candidate-list:not(.existing-collaborator-list)");
    // Only jsmith and pu_jane are eligible: owner_user is the owner,
    // existing_member is already a collaborator, disabled_user is disabled,
    // and another_admin isn't a User/Power User.
    await expect(list.locator("li")).toHaveCount(2);
    await expect(list.getByText("owner_user")).toHaveCount(0);
    await expect(list.getByText("existing_member")).toHaveCount(0);
    await expect(list.getByText("disabled_user")).toHaveCount(0);
    await expect(list.getByText("another_admin")).toHaveCount(0);

    await list.getByText("jsmith").click();
    await list.getByText("pu_jane").click();
    await page.getByRole("button", { name: /^Add 2 collaborators$/ }).click();

    await expect(page.getByText("2 collaborator(s) added.")).toBeVisible();
    expect(postedUserIds.sort()).toEqual(["pu-1", "u-1"]);
  });
});
