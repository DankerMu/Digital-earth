import { defineConfig, devices } from '@playwright/test';

const PORT = 4173;
const baseURL = `http://127.0.0.1:${PORT}`;

const noProxyHosts = '127.0.0.1,localhost';
const existingNoProxy = process.env.NO_PROXY ?? process.env.no_proxy;
const mergedNoProxy = existingNoProxy ? `${existingNoProxy},${noProxyHosts}` : noProxyHosts;
process.env.NO_PROXY = mergedNoProxy;
process.env.no_proxy = mergedNoProxy;

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  timeout: 120_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    launchOptions: {
      args: [
        '--no-proxy-server',
        ...(process.env.CI ? ['--use-gl=swiftshader', '--ignore-gpu-blocklist'] : []),
      ],
    },
  },
  webServer: {
    command: 'pnpm run build && pnpm run preview --host 127.0.0.1 --port 4173 --strictPort',
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      ...process.env,
      VITE_E2E: 'true',
    },
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
