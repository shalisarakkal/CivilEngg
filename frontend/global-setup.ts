import fs from "node:fs";
import path from "node:path";
import { request } from "@playwright/test";

/**
 * Logs in as the e2e Power User account (seeded by
 * backend/scripts/e2e_bootstrap.py) via the API and saves the resulting
 * session cookie as a Playwright storageState file. playwright.config.ts
 * applies it globally, so full-workflow.spec.ts and phase9.spec.ts (which
 * exercise the real backend, unlike workspace.spec.ts's mocked routes)
 * don't need a UI login step inserted into every test.
 *
 * Power User, not Admin: it's the role these two specs actually need
 * (create/own/archive/purge a project) without granting more than that.
 */

// Keep in sync with backend/scripts/e2e_bootstrap.py's E2E_PASSWORD/E2E_ACCOUNTS.
const E2E_PASSWORD = "e2e-fixed-password-1";
const E2E_EMAIL = "e2e-power-user@example.com";
const API_URL = "http://localhost:8000";

export const AUTH_DIR = path.join(__dirname, "playwright", ".auth");
export const POWER_USER_STORAGE_STATE = path.join(AUTH_DIR, "power-user.json");

export default async function globalSetup(): Promise<void> {
  const context = await request.newContext({ baseURL: API_URL });
  try {
    const response = await context.post("/auth/login", {
      data: { email: E2E_EMAIL, password: E2E_PASSWORD },
    });
    if (!response.ok()) {
      throw new Error(
        `e2e global setup: login as e2e-power-user failed (HTTP ${response.status()}). ` +
          "Is the backend webServer (which runs e2e_bootstrap.py) up yet?",
      );
    }
    fs.mkdirSync(AUTH_DIR, { recursive: true });
    await context.storageState({ path: POWER_USER_STORAGE_STATE });
  } finally {
    await context.dispose();
  }
}
