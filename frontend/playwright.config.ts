import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 30000,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env['SAA_APP_URL'] ?? 'http://127.0.0.1:8080',
    ...(process.env['PLAYWRIGHT_CHANNEL'] ? { channel: process.env['PLAYWRIGHT_CHANNEL'] } : {}),
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
