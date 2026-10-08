import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';
import { track } from '../helpers/track';

/**
 * Every funnel card draws its funnel, and a step only counts visitors who
 * reached the steps before it: the one who went straight to the cart is in
 * nobody's count but their own.
 */
test('a funnel card counts a step only for visitors through the steps before it', async ({ page, request }) => {
  const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
  const cookie = { Cookie: `session_token=${sessionToken}` };
  const created = await request.post(`/api/v1/funnels?website_id=${websiteId}`, {
    data: { name: 'Checkout', steps: [
      { step: 1, name: 'Product', path: '/product' },
      { step: 2, name: 'Cart', path: '/cart' },
    ] },
    headers: cookie,
  });
  expect(created.ok(), await created.text()).toBeTruthy();

  const visit = (path: string, who: string) => track(
    request, { tracking_code: trackingCode, path },
    `Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0 Safari/537.36 ${who}`,
  );
  await visit('/product', 'shopper');
  await visit('/cart', 'shopper');
  await visit('/cart', 'straight-to-cart');

  await page.goto('/login');
  await page.evaluate((t) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
  await page.goto(`/dashboard/website/${websiteId}/funnels`);

  const card = page.locator('.funnel-card');
  await expect(card).toHaveCount(1);
  await expect(card.locator('li')).toHaveCount(2);
  await expect(card.locator('li').nth(0)).toContainText('1');
  await expect(card.locator('li').nth(1)).toContainText('100%');   // 1 of 1, not 2 of 1
  await expect(card).toContainText('100.0%');

  // The period switch reloads every card.
  const week = page.getByRole('button', { name: '7 days' });
  await week.click();
  await expect(week).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: '30 days' })).toHaveAttribute('aria-pressed', 'false');
  await expect(card).toContainText('100.0%');
});
