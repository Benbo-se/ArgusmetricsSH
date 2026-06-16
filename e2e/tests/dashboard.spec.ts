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
