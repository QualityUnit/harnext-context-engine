import { defineConfig, devices } from "@playwright/test";

// e2e runs against `next dev` (port 3100, the project's usual web port) talking to
// the zero-dependency mock API (port 8000, the app's default API base) so the
// routing tests need no real backend, database, or network.
const WEB_PORT = 3100;
const API_PORT = 8000;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      // Use the system Chrome so CI/dev needs no bundled-browser download.
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
  webServer: [
    {
      command: `node e2e/mock-api.mjs ${API_PORT}`,
      port: API_PORT,
      reuseExistingServer: !process.env.CI,
      stdout: "ignore",
    },
    {
      command: `pnpm exec next dev --port ${WEB_PORT}`,
      port: WEB_PORT,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
