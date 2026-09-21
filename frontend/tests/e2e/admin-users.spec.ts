import { test, expect, Page, Route } from "@playwright/test";

const API = "http://localhost:8000";

const MOCK_ADMIN = {
  id: "88888888-8888-8888-8888-888888888888",
  username: "mock-admin",
  role: "admin",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  disabled_at: null,
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockBaseline(page: Page, users: unknown[] = []) {
  await page.route(`${API}/auth/me`, (route) => json(route, MOCK_ADMIN));
  await page.route(`${API}/users`, async (route) => {
    if (route.request().method() === "GET") return json(route, users);
    return route.continue();
  });
}

test.describe("admin users: create user", () => {
  test("new password and confirm password must match before submitting", async ({ page }) => {
    await mockBaseline(page);
    let postCalls = 0;
    await page.route(`${API}/users`, async (route) => {
      if (route.request().method() === "POST") {
        postCalls += 1;
        return json(route, {}, 201);
      }
      return route.continue();
    });

    await page.goto("/admin/users");
    await expect(page.getByRole("heading", { name: "Manage users" })).toBeVisible();

    await page.locator("#new-username").fill("jsmith");
    await page.getByPlaceholder("Email").fill("jsmith@example.com");
    await page.getByPlaceholder("Password (min. 8 characters)").fill("password123");
    await page.getByPlaceholder("Confirm password").fill("does-not-match");
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page.getByText("New password and confirm password do not match.")).toBeVisible();
    expect(postCalls).toBe(0);
  });

  test("matching password and confirm password creates the user", async ({ page }) => {
    await mockBaseline(page);
    let postBody: unknown = null;
    const createdUser = {
      id: "new-user-id",
      username: "jsmith",
      email: "jsmith@example.com",
      role: "user",
      disabled_at: null,
    };
    const users: unknown[] = [];
    await page.route(`${API}/users`, async (route) => {
      if (route.request().method() === "POST") {
        postBody = route.request().postDataJSON();
        users.push(createdUser);
        return json(route, createdUser, 201);
      }
      return json(route, users);
    });

    await page.goto("/admin/users");
    await page.locator("#new-username").fill("jsmith");
    await page.getByPlaceholder("Email").fill("jsmith@example.com");
    await page.getByPlaceholder("Password (min. 8 characters)").fill("password123");
    await page.getByPlaceholder("Confirm password").fill("password123");
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page.getByText("jsmith", { exact: true })).toBeVisible();
    expect(postBody).toEqual({
      username: "jsmith",
      email: "jsmith@example.com",
      password: "password123",
      role: "user",
    });
    // Fields, including confirm password, are cleared on success.
    await expect(page.locator("#new-username")).toHaveValue("");
    await expect(page.getByPlaceholder("Password (min. 8 characters)")).toHaveValue("");
    await expect(page.getByPlaceholder("Confirm password")).toHaveValue("");
  });
});
