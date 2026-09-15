import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

// NEXT_PUBLIC_API_URL is normally supplied as a real environment variable
// (see playwright.config.ts). For local `npm run dev`, README.md instead has
// developers copy the repo-root .env.example to .env — but Next.js only
// reads .env files from this directory, not the repo root, so that value
// would otherwise be silently ignored and the frontend would always fall
// back to its hardcoded default. Read it directly as a fallback so the
// documented setup flow actually works.
function readRootEnvApiUrl(): string | undefined {
  const rootEnvPath = path.join(__dirname, "..", ".env");
  if (!existsSync(rootEnvPath)) return undefined;
  const match = readFileSync(rootEnvPath, "utf-8").match(/^NEXT_PUBLIC_API_URL=(.*)$/m);
  return match?.[1]?.trim();
}

const resolvedApiUrl = process.env.NEXT_PUBLIC_API_URL ?? readRootEnvApiUrl();

const nextConfig: NextConfig = {
  env: resolvedApiUrl ? { NEXT_PUBLIC_API_URL: resolvedApiUrl } : {},
};

export default nextConfig;
