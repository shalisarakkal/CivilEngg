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

test.describe("admin users: edit email", () => {
  const EXISTING_USER = {
    id: "existing-user-id",
    username: "jsmith",
    email: "jsmith@old.example.com",
    role: "user",
    disabled_at: null,
  };

  test("Edit email opens prefilled with the current email and PATCHes the new one", async ({
    page,
  }) => {
    const users = [{ ...EXISTING_USER }];
    let patchBody: unknown = null;
    await page.route(`${API}/auth/me`, (route) => json(route, MOCK_ADMIN));
    await page.route(`${API}/users`, (route) => json(route, users));
    await page.route(`${API}/users/${EXISTING_USER.id}`, async (route) => {
      if (route.request().method() === "PATCH") {
        patchBody = route.request().postDataJSON();
        users[0] = { ...users[0], email: "jsmith@new.example.com" };
        return json(route, users[0]);
      }
      return route.continue();
    });

    await page.goto("/admin/users");
    await expect(page.getByText("jsmith@old.example.com")).toBeVisible();

    await page.getByRole("button", { name: "Edit email" }).click();
    await expect(page.getByRole("heading", { name: "Edit email for jsmith?" })).toBeVisible();
    await expect(page.locator("#edit-email")).toHaveValue("jsmith@old.example.com");

    await page.locator("#edit-email").fill("jsmith@new.example.com");
    await page.getByRole("button", { name: "Save email" }).click();

    expect(patchBody).toEqual({ email: "jsmith@new.example.com" });
    await expect(page.getByRole("heading", { name: "Edit email for jsmith?" })).not.toBeVisible();
    await expect(page.getByText("jsmith@new.example.com")).toBeVisible();
  });

  test("a duplicate email surfaces the server's error and leaves the modal open", async ({
    page,
  }) => {
    await page.route(`${API}/auth/me`, (route) => json(route, MOCK_ADMIN));
    await page.route(`${API}/users`, (route) => json(route, [EXISTING_USER]));
    await page.route(`${API}/users/${EXISTING_USER.id}`, (route) =>
      json(route, { detail: "Email already exists" }, 409),
    );

    await page.goto("/admin/users");
    await page.getByRole("button", { name: "Edit email" }).click();
    await page.locator("#edit-email").fill("taken@example.com");
    await page.getByRole("button", { name: "Save email" }).click();

    await expect(page.getByText("Email already exists")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Edit email for jsmith?" })).toBeVisible();
  });
});
