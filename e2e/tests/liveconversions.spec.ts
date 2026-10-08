import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * A goal converting is announced on the goals page as it happens: a toast,
 * the goal's card rings, and its count goes up without a reload.
 */
test('a conversion shows up as a toast, and the goal card rings and counts it', async ({ page, request }) => {
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  const created = await request.post(`/api/v1/analytics/goals?website_id=${websiteId}`, {
    data: { name: 'Order placed', event_name: 'order_placed' },
    headers: { Cookie: `session_token=${sessionToken}` },
  });
  expect(created.ok(), await created.text()).toBeTruthy();

  await page.goto('/login');
  await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
  await page.goto(`/dashboard/website/${websiteId}/goals`);
  await expect(page.locator('.goal-card')).toHaveCount(1);
  await expect(page.locator('.goal-count')).toHaveText('0');
  await page.waitForTimeout(500);  // the socket opens

  await request.post('/api/v1/analytics/track-event', {
    data: { tracking_code: trackingCode, event_name: 'order_placed' },
    headers: { 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0 Safari/537.36' },
  });

  await expect(page.getByText('🎯 Order placed just converted')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('.goal-card').first()).toHaveClass(/goal-pulse/);
  await expect(page.locator('.goal-count')).toHaveText('1');
});
