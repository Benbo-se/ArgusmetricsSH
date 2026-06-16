import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createVerifiedUser } from '../helpers/auth';

test.describe('Billing Page', () => {
  test('billing page renders for authenticated user', async ({ page, request }) => {
    const { sessionToken } = await createVerifiedUser(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto('/billing');
    await expect(page.locator('text=Current Plan').first()).toBeVisible({ timeout: 10000 });
  });

  test('billing page shows usage information', async ({ page, request }) => {
    const { sessionToken } = await createVerifiedUser(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto('/billing');
    // Should show pageview usage
    await expect(page.locator('text=Pageview').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Monthly Usage API', () => {
  test('GET /auth/me/monthly-usage returns usage data', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    const res = await request.get('/api/v1/auth/me/monthly-usage', {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.monthly_pageviews).toBeDefined();
    expect(body.plan).toBeDefined();
  });
});

test.describe('Stripe Config', () => {
  test('GET /stripe/config returns config', async ({ request }) => {
    const res = await request.get('/api/v1/stripe/config');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('configured');
  });
});
