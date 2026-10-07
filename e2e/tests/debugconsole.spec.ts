import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * The live debug console shows real traffic, not only its own test pings.
 */
test('a real pageview arrives as a new row with its outcome', async ({ page, request }) => {
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  await page.goto('/login');
  await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
  await page.goto(`/dashboard/website/${websiteId}/debug`);
  await expect(page.getByText('Connected', { exact: true })).toBeVisible({ timeout: 10000 });

  await request.post('/api/v1/analytics/track', {
    data: { tracking_code: trackingCode, path: '/from-a-real-visit' },
    headers: { 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0 Safari/537.36' },
  });

  const row = page.locator('tbody tr', { hasText: '/from-a-real-visit' });
  await expect(row).toBeVisible({ timeout: 5000 });
  await expect(row).toHaveClass(/dbg-row-in/);
  await expect(row.getByText('recorded', { exact: true })).toBeVisible();
  // Real traffic carries the browser family, not the test ping's device field.
  await expect(row).toContainText('Chrome');
});

test('the details dialog opens, and Escape closes it', async ({ page, request }) => {
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  await page.goto('/login');
  await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
  await page.goto(`/dashboard/website/${websiteId}/debug`);
  await expect(page.getByText('Connected', { exact: true })).toBeVisible({ timeout: 10000 });

  await request.post('/api/v1/analytics/track', {
    data: { tracking_code: trackingCode, path: '/details' },
    headers: { 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0 Safari/537.36' },
  });
  await page.locator('tbody tr', { hasText: '/details' }).getByRole('button', { name: /View/ }).click();

  // With @click.away on the backdrop root, the backdrop could not close it
  // and Escape did nothing.
  await expect(page.getByText('Event Details')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByText('Event Details')).toBeHidden();
});
