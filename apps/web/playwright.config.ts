import { defineConfig, devices } from "@playwright/test";

const bffPort = Number(process.env.ONEIROI_E2E_BFF_PORT ?? 8000);
const webPort = Number(process.env.ONEIROI_E2E_WEB_PORT ?? 5173);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: [
    {
      command: `cd ../.. && uv run uvicorn oneiroi_bff.main:app --host 127.0.0.1 --port ${bffPort}`,
      url: `http://127.0.0.1:${bffPort}/healthz`,
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: `pnpm dev --host 127.0.0.1 --port ${webPort}`,
      url: `http://127.0.0.1:${webPort}`,
      env: {
        ...process.env,
        ONEIROI_API_PROXY_TARGET: `http://127.0.0.1:${bffPort}`,
      },
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
