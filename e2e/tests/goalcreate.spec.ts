import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * Creating a goal, typed the way a person types.
 *
 * Two things went wrong here in production and neither showed up in a test
 * that filled the field in one go:
 *
 *   - the event name was derived from the first keystroke, so "Finding
 *     proven" saved as "f" and matched nothing the site ever sent
 *   - opening the dialog cleared it, and on a slow load that reset landed
 *     after the first characters, leaving an empty form that the browser's
 *     own validation then refused to submit
 */
test('a goal typed character by character saves with the right event name',
  async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);
    await page.goto('/login');
    await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);

    let saved: any = null;
    page.on('response', async r => {
      if (r.url().includes('/goals') && r.request().method() === 'POST' && r.ok()) {
        saved = await r.json().catch(() => null);
      }
    });

    await page.goto(`/dashboard/website/${websiteId}/goals`);
    await page.getByRole('button', { name: /Create.*Goal/i }).first().click();
    await page.locator('input').first().pressSequentially('Finding proven', { delay: 25 });
    await page.getByRole('button', { name: /^Create Goal$/ }).click();
    await page.waitForTimeout(2500);

    expect(saved, 'the goal was never saved').not.toBeNull();
    expect(saved.event_name, 'the event name was truncated to the first keystroke')
      .toBe('finding_proven');
    await expect(page.locator('tbody tr')).toHaveCount(1);
  });

test('typing immediately after opening does not lose the input',
  async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);
    await page.goto('/login');
    await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
    await page.goto(`/dashboard/website/${websiteId}/goals`);

    // No wait between opening and typing, which is what a fast typist does
    // and what the reset-on-open race needed to lose the first characters.
    await page.getByRole('button', { name: /Create.*Goal/i }).first().click();
    await page.locator('input').first().pressSequentially('Checkout reached', { delay: 5 });

    await expect(page.locator('input').first()).toHaveValue('Checkout reached');
  });
