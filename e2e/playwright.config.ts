import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  retries: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:8020',
    extraHTTPHeaders: {
      'Accept': 'application/json',
    },
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'api',
      testMatch: /api\.spec\.ts/,
    },
    {
      name: 'tracking',
      testMatch: /tracking\.spec\.ts/,
    },
    {
      name: 'auth',
      testMatch: /auth\.spec\.ts/,
    },
    {
      name: 'dashboard',
      testMatch: /dashboard\.spec\.ts/,
      dependencies: ['auth'],
    },
    {
      name: 'landing',
      testMatch: /landing\.spec\.ts/,
    },
    {
      name: 'public-dashboard',
      testMatch: /public-dashboard\.spec\.ts/,
    },
    {
      name: 'billing',
      testMatch: /billing\.spec\.ts/,
      dependencies: ['auth'],
    },
    {
      name: 'ecommerce',
      testMatch: /ecommerce\.spec\.ts/,
    },
    {
      name: 'stripe',
      testMatch: /stripe\.spec\.ts/,
      dependencies: ['auth'],
    },
    {
      name: 'team',
      testMatch: /team\.spec\.ts/,
      dependencies: ['auth'],
    },
    {
      name: 'advanced-features',
      testMatch: /advanced-features\.spec\.ts/,
      dependencies: ['auth'],
    },
  ],
});
