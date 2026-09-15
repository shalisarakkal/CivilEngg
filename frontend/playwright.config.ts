import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const dataDir = path.join(__dirname, ".e2e-data").split(path.sep).join("/");
const databaseUrl = `sqlite:///${dataDir}/e2e.db`;
const storagePath = `${dataDir}/storage`;

export default defineConfig({
  testDir: "./tests/e2e",
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
