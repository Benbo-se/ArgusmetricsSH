import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * Inviting somebody, on an instance with no email configured.
 *
 * That is the normal case for a self-hosted instance, and it is the only case
 * where the invitation link has to be shown rather than sent. It used to go
 * into a toast that cleared itself after five seconds, taking the only copy
 * of the link with it.
 */

test('inviting shows a link that stays on screen', async ({ page, request }) => {
  const { sessionToken, websiteId } = await createUserWithWebsite(request);

  await page.goto('/login');
  await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);

  await page.goto(`/dashboard/website/${websiteId}/team`);
  await page.getByRole('button', { name: /Invite/i }).first().click();

  const email = `client-${Date.now()}@example.com`;
  await page.locator('#invite-email, input[type=email]').first().fill(email);
  await page.getByRole('button', { name: 'Send Invitation' }).click();

  const link = page.locator('input[readonly]');
  await expect(link).toBeVisible({ timeout: 8000 });
  const value = await link.inputValue();
  expect(value).toContain('/accept-invite?token=');

  // Still there well after a toast would have gone.
  await page.waitForTimeout(6000);
  await expect(link).toBeVisible();
});
