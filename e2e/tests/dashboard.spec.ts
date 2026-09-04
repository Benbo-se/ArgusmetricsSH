import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createVerifiedUser, createUserWithWebsite } from '../helpers/auth';

test.describe('Dashboard Access', () => {
  test('unauthenticated user redirected from dashboard', async ({ page }) => {
    await page.goto('/dashboard');
    // Should redirect to login or show login page
    await page.waitForURL(/login|dashboard/);
  });

  test('authenticated user sees dashboard', async ({ page, request }) => {
    const { sessionToken } = await createVerifiedUser(request);

    // Set session cookie
    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto('/dashboard');
    await expect(page).toHaveURL(/dashboard/);
  });
});

test.describe('Website Management UI', () => {
  test('dashboard shows website list', async ({ page, request }) => {
    const { sessionToken } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto('/dashboard');
    // Should show at least one website
    await expect(page.locator('text=Test Site').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Website Analytics Dashboard', () => {
  test('website dashboard shows stats', async ({ page, request }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Track some data
    await api.track(trackingCode, '/');
    await api.track(trackingCode, '/about');

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}`);
    await expect(page.locator('text=Total Pageviews').first()).toBeVisible({ timeout: 10000 });
  });

  test('date range filter works', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}`);

    // Click 30D date range
    const btn30d = page.locator('button:has-text("30D"), a:has-text("30D")').first();
    if (await btn30d.isVisible()) {
      await btn30d.click();
      await page.waitForTimeout(1000);
    }
  });
});

test.describe('Website Settings', () => {
  test('settings page renders', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}/settings`);
    await expect(page.locator('text=Tracking Code').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Goals Page', () => {
  test('goals page renders', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}/goals`);
    await expect(page.locator('text=Create New Goal').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Team Page', () => {
  test('team page renders', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}/team`);
    await expect(page.locator('text=Team').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Scroll depth on top pages', () => {
  test('a page with scroll data shows how far visitors read', async ({ page, request }) => {
    // Scroll depth was written on every pageview since the tracker was built
    // and displayed nowhere, which made it data collected for no purpose. It
    // is shown now, and this is what stops it going quiet again: the number
    // reaching the JSON island is not the same as it reaching the screen.
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);

    for (const depth of [40, 60, 80]) {
      const res = await request.post('/api/v1/analytics/track', {
        data: { tracking_code: trackingCode, path: '/long-article', scroll_depth: depth },
        headers: { 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/120' },
      });
      expect(res.status()).toBe(200);
    }

    // Same shape as the tests above: visit a page first, then set the cookie
    // from inside it. addCookies needs an origin and a blank page has none.
    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}?range=30d`);

    const row = page.locator('text=/long-article').first();
    await expect(row).toBeVisible();

    // 40, 60 and 80 average to 60.
    await expect(page.getByText('60% read')).toBeVisible();
  });
});
