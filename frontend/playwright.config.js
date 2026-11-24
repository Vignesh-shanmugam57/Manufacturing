import { defineConfig } from "@playwright/test";

// End-to-end tests drive the real app (React -> FastAPI -> Domo AI -> PostgreSQL) in Microsoft Edge.
// Existing servers are reused; otherwise Playwright starts the backend (uv) and the Vite dev server.
export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 20_000 },
  workers: 1,
  reporter: [["list"]],
  outputDir: "test-results/artifacts",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:5173",
    channel: "msedge",
    headless: true,
    // the 3D digital twin needs WebGL; headless Edge gets it from the software renderer
    launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] },
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  // With E2E_BASE_URL set the servers are assumed to be running already (e.g. FastAPI serving the build).
  webServer: process.env.E2E_BASE_URL ? [] : [
    {
      command: "uv run python -m uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/api/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "npx vite --port 5173",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
