import path from "node:path";
import { defineConfig, devices } from "@playwright/test";
import { POWER_USER_STORAGE_STATE } from "./global-setup";

// This SQLite database persists across local runs (each spec uses unique
// project names to tolerate that -- see full-workflow.spec.ts). Its schema
// only ever grows via Base.metadata.create_all (scripts/e2e_bootstrap.py),
// which creates missing tables but never alters existing ones -- so after
// a real schema change (new column/table), delete .e2e-data/ once locally
// or you'll hit a confusing "table X has no column named Y" 500 from
// stale leftover tables, not from anything wrong with the change itself.
const dataDir = path.join(__dirname, ".e2e-data").split(path.sep).join("/");
const databaseUrl = `sqlite:///${dataDir}/e2e.db`;
const storagePath = `${dataDir}/storage`;

export default defineConfig({
  testDir: "./tests/e2e",
  // Logs in as the seeded e2e Power User account via the API and saves a
  // storageState (see global-setup.ts), applied to every test below via
  // use.storageState -- so full-workflow.spec.ts/phase9.spec.ts (which hit
  // the real backend) start already authenticated, with no UI login step
  // in each test. workspace.spec.ts mocks the API entirely (including its
  // own /auth/me route) and doesn't depend on this, but having a real
  // session cookie present alongside its mocks is harmless.
  globalSetup: "./global-setup.ts",
  // The full-workflow spec exercises a single live SQLite-backed backend
  // process; run sequentially to avoid "database is locked" contention
  // between test workers (SQLite has no busy-timeout configured here).
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    storageState: POWER_USER_STORAGE_STATE,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        "uv run python scripts/e2e_bootstrap.py && uv run uvicorn --app-dir src civil_engineering.main:app --port 8000",
      cwd: path.join(__dirname, "..", "backend"),
      env: { DATABASE_URL: databaseUrl, LOCAL_STORAGE_PATH: storagePath },
      url: "http://localhost:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- --port 3000",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
