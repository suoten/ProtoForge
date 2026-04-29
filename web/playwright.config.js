import { defineConfig } from 'playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
  webServer: process.env.CI ? {
    command: 'cd .. && pip install -e ".[all]" && PROTOFORGE_NO_AUTH=1 protoforge run --port 8765',
    port: 8765,
    reuseExistingServer: !process.env.CI,
    timeout: 60000,
  } : undefined,
});
