import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * A website that has never recorded anything shows the first-visit guide, and
 * the guide notices the first pageview without a reload: it listens on
 * /ws/live, which nothing used to send to.
 */
test('the guide turns over the moment the first visit is recorded', async ({ page, request }) => {
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  await page.goto('/login');
  await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
  await page.goto(`/dashboard/website/${websiteId}`);

  await expect(page.getByText('Waiting for the first visit')).toBeVisible();
  await expect(page.locator('#fv-snippet')).toContainText(trackingCode);
  // Give the socket a moment to open before the visit, as a person would.
  await page.waitForTimeout(500);

  const response = await request.post('/api/v1/analytics/track', {
    data: { tracking_code: trackingCode, path: '/hello-world' },
    headers: { 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0 Safari/537.36' },
  });
  expect(response.ok(), await response.text()).toBeTruthy();

  await expect(page.getByText('Your first visit is here')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('.fv-arrived code')).toHaveText('/hello-world');

  // With a pageview on record, the dashboard is a dashboard again.
  await page.getByRole('button', { name: 'Show my dashboard' }).click();
  await expect(page.getByText('Waiting for the first visit')).toHaveCount(0);
});
