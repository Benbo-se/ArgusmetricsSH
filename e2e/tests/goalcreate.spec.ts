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

/**
 * #113, as reported: three goals in a row saved, the fourth did not, with no
 * error. The dialog was in the DOM but not on screen. Opening it left focus on
 * the button that opened it; a space typed there clicked that button again,
 * and @click.away took the click for one outside the dialog and closed it.
 */
test('four goals in a row in one session all save', async ({ page, request }) => {
  const { sessionToken, websiteId } = await createUserWithWebsite(request);
  await page.goto('/login');
  await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
  await page.goto(`/dashboard/website/${websiteId}/goals`);

  for (const name of ['Order placed', 'Table booked', 'Menu opened', 'Call clicked']) {
    await page.getByRole('button', { name: /Create.*Goal/i }).first().click();
    // Typed without clicking the field first: the dialog has to put the
    // cursor there itself, or the space in the name lands on the button.
    await page.keyboard.type(name, { delay: 10 });
    await page.keyboard.press('Enter');
    await expect(page.getByText(name, { exact: true })).toBeVisible({ timeout: 5000 });
  }

  await expect(page.locator('tbody tr')).toHaveCount(4);
});

test('a Swedish goal name gives an event name without underscores for å ä ö',
  async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);
    await page.goto('/login');
    await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
    await page.goto(`/dashboard/website/${websiteId}/goals`);

    await page.getByRole('button', { name: /Create.*Goal/i }).first().click();
    await page.locator('input').first().pressSequentially('Beställ via Wolt', { delay: 10 });

    await expect(page.locator('form input').nth(1)).toHaveValue('bestall_via_wolt');
  });
