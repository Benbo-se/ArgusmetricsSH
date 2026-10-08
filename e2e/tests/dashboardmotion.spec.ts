import { test, expect, Page, APIRequestContext } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';
import { track } from '../helpers/track';

/**
 * The headline numbers count up, and a refresh that changes one counts from
 * the old value to the new and marks the tile. Recorded with a mutation
 * observer installed before the page loads, so the test reads what the page
 * did without timing anything itself.
 */
const UA = 'Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0 Safari/537.36';

async function visits(request: APIRequestContext, code: string, n: number) {
  for (let i = 0; i < n; i++) {
    await track(request, { tracking_code: code, path: `/p${i}` }, UA);
  }
}

async function watchPageviews(page: Page) {
  await page.addInitScript(() => {
    (window as any).__seen = [];
    new MutationObserver(() => {
      document.querySelectorAll('.stat-tile').forEach((t) => {
        if (t.querySelector('.stat-label')?.textContent?.trim() === 'Total Pageviews') {
          (window as any).__seen.push(t.querySelector('.stat-value')?.textContent?.trim());
        }
      });
    }).observe(document, { subtree: true, childList: true, characterData: true });
  });
}

async function openDashboard(page: Page, token: string, id: number) {
  await page.goto('/login');
  await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, token);
  await page.goto(`/dashboard/website/${id}`);
}

const pageviews = (page: Page) => page.locator('.stat-tile', { hasText: 'Total Pageviews' }).locator('.stat-value');

test('the numbers count up to the server value', async ({ page, request }) => {
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  await visits(request, trackingCode, 12);
  await watchPageviews(page);
  await openDashboard(page, sessionToken, websiteId);

  await expect(pageviews(page)).toHaveText('12');
  const seen: string[] = await page.evaluate(() => (window as any).__seen);
  expect(seen.some((v) => v !== '12' && /^\d+$/.test(v)), `never counted: ${seen.join(',')}`).toBeTruthy();
});

test('prefers-reduced-motion shows the number and nothing in between', async ({ page, request }) => {
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  await visits(request, trackingCode, 12);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await watchPageviews(page);
  await openDashboard(page, sessionToken, websiteId);

  await expect(pageviews(page)).toHaveText('12');
  await page.waitForTimeout(900);
  const seen: string[] = await page.evaluate(() => (window as any).__seen);
  expect(seen.filter((v) => v && v !== '12'), seen.join(',')).toEqual([]);
});

test('a refresh that changes a number marks its tile', async ({ page, request }) => {
  test.setTimeout(40000);
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  await visits(request, trackingCode, 3);
  await openDashboard(page, sessionToken, websiteId);
  await expect(pageviews(page)).toHaveText('3');

  await visits(request, trackingCode, 2);
  // The tiles refresh every ten seconds.
  await expect(pageviews(page)).toHaveText('5', { timeout: 15000 });
  await expect(page.locator('.stat-tile', { hasText: 'Total Pageviews' })).toHaveClass(/stat-bump/);
});

test('a hidden tab shows the real numbers, not a count frozen on its first frame', async ({ page, request }) => {
  // A hidden tab runs no animation frames. The public dashboard, opened in a
  // background tab, read 0 visitors until someone looked at it.
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  await visits(request, trackingCode, 12);
  await page.addInitScript(() => {
    Object.defineProperty(document, 'hidden', { get: () => true });
    Object.defineProperty(document, 'visibilityState', { get: () => 'hidden' });
  });
  await watchPageviews(page);
  await openDashboard(page, sessionToken, websiteId);

  await expect(pageviews(page)).toHaveText('12');
  const seen: string[] = await page.evaluate(() => (window as any).__seen);
  expect(seen.filter((v) => v && v !== '12'), seen.join(',')).toEqual([]);
});
