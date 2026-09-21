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

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockAuthMe(page: Page) {
  await page.route(`${API}/auth/me`, (route) => json(route, MOCK_CURRENT_USER));
}

test.describe("account: change password", () => {
  test("new password and confirm password must match before submitting", async ({ page }) => {
    await mockAuthMe(page);
    let patchCalls = 0;
    await page.route(`${API}/auth/password`, async (route) => {
      patchCalls += 1;
      return json(route, {}, 204);
    });

    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "My account" })).toBeVisible();

    await page.locator("#current-password").fill("old-password-123");
    await page.locator("#new-password").fill("new-password-123");
    await page.locator("#confirm-password").fill("does-not-match-456");
    await page.getByRole("button", { name: "Change password" }).click();

    await expect(page.getByText("New password and confirm password do not match.")).toBeVisible();
    // The mismatch must be caught client-side, before any request is sent --
    // not just reported after a round trip.
    expect(patchCalls).toBe(0);
  });

  test("matching new and confirm password submits and shows success", async ({ page }) => {
    await mockAuthMe(page);
    let patchBody: unknown = null;
    await page.route(`${API}/auth/password`, async (route) => {
      patchBody = route.request().postDataJSON();
      return json(route, {}, 204);
    });

    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "My account" })).toBeVisible();

    await page.locator("#current-password").fill("old-password-123");
    await page.locator("#new-password").fill("new-password-123");
    await page.locator("#confirm-password").fill("new-password-123");
    await page.getByRole("button", { name: "Change password" }).click();

    await expect(page.getByText("Password changed.")).toBeVisible();
    expect(patchBody).toEqual({
      current_password: "old-password-123",
      new_password: "new-password-123",
    });
    // Fields are cleared on success, including the new confirm-password one.
    await expect(page.locator("#current-password")).toHaveValue("");
    await expect(page.locator("#new-password")).toHaveValue("");
    await expect(page.locator("#confirm-password")).toHaveValue("");
  });

  test("a server-rejected current password still surfaces the server's error", async ({ page }) => {
    await mockAuthMe(page);
    await page.route(`${API}/auth/password`, (route) =>
      json(route, { detail: "Current password is incorrect." }, 400),
    );

    await page.goto("/account");
    await page.locator("#current-password").fill("wrong-password");
    await page.locator("#new-password").fill("new-password-123");
    await page.locator("#confirm-password").fill("new-password-123");
    await page.getByRole("button", { name: "Change password" }).click();

    await expect(page.getByText("Current password is incorrect.")).toBeVisible();
  });
});
