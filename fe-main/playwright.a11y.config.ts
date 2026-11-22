import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  testMatch: "accessibility.spec.ts",
  testIgnore: [],
  workers: 1,
  webServer: [
    { command: "node e2e/a11y-api.mjs", url: "http://127.0.0.1:8000/health", reuseExistingServer: false },
    { command: "pnpm build && pnpm start --port 3100", url: "http://127.0.0.1:3100", reuseExistingServer: !process.env.CI, timeout: 180_000 },
  ],
});
