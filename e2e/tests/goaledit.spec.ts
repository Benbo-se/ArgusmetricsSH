import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * Editing a goal, and typing an event name by hand.
 *
 * Both faults come from the same place: a row component's getters share names
 * with the page component's data fields, so an assignment made from a row's
 * scope lands on a getter that has no setter and disappears.
 */
async function signIn(page: any, request: any) {
  const { sessionToken, websiteId } = await createUserWithWebsite(request);
  await page.goto('/login');
  await page.evaluate((t: string) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
  await page.goto(`/dashboard/website/${websiteId}/goals`);
  return websiteId;
}

async function createGoal(page: any, name: string) {
  await page.getByRole('button', { name: /Create.*Goal/i }).first().click();
  await page.locator('input').first().pressSequentially(name, { delay: 20 });
  await page.getByRole('button', { name: /^Create Goal$/ }).click();
  await expect(page.locator('tbody tr')).toHaveCount(1, { timeout: 8000 });
}

test('Edit opens the dialog with the goal already in it', async ({ page, request }) => {
  await signIn(page, request);
  await createGoal(page, 'Quote Requested');

  await page.getByRole('button', { name: /^Edit$/i }).first().click();
  await page.waitForTimeout(400);

  const values = await page.locator('form input').evaluateAll(
    els => els.map(e => (e as HTMLInputElement).value));
  console.log('FALT_VID_EDIT=' + JSON.stringify(values));

  expect(values[0], 'the goal name was not prefilled').toBe('Quote Requested');
  expect(values[1], 'the event name was not prefilled').toBe('quote_requested');
});

test('typing an event name replaces the suggestion instead of appending',
  async ({ page, request }) => {
    await signIn(page, request);

    await page.getByRole('button', { name: /Create.*Goal/i }).first().click();
    await page.locator('input').first().pressSequentially('Quote Requested', { delay: 20 });

    // The natural thing to do: it is a required field with a placeholder, so
    // people click it and type what they mean.
    const eventField = page.locator('form input').nth(1);
    await eventField.click();
    await eventField.pressSequentially('quote_requested', { delay: 20 });

    const value = await eventField.inputValue();
    console.log('HANDSKRIVET=' + JSON.stringify(value));
    expect(value, 'the typed name was appended to the suggestion')
      .toBe('quote_requested');
  });
