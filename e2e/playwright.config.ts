import { defineConfig } from '@playwright/test';

// Two origins, because the product is two things. The backend serves the app
// and its API; the marketing site is a separate set of static pages served
// elsewhere. They shared one origin behind nginx when these tests were
// written, which is why the landing suite used to point at the app and get a
// redirect to /login.
const APP_URL = process.env.BASE_URL || 'http://127.0.0.1:8020';
const SITE_URL = process.env.SITE_URL || 'http://127.0.0.1:8099';

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  retries: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: APP_URL,
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
      name: 'invite',
      testMatch: /invite\.spec\.ts/,
      dependencies: ['auth'],
    },
    {
      // Reads the browser console. Alpine's CSP build does not throw on an
      // expression it cannot evaluate, it warns and renders nothing, so this
      // is the only project that can catch a silently dead control.
      name: 'csp',
      testMatch: /csp\.spec\.ts/,
      dependencies: ['auth'],
    },
    {
      name: 'landing',
      testMatch: /landing\.spec\.ts/,
      use: { baseURL: SITE_URL },
    },
    {
      name: 'public-dashboard',
      testMatch: /public-dashboard\.spec\.ts/,
    },
    {
      name: 'ecommerce',
      testMatch: /ecommerce\.spec\.ts/,
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
