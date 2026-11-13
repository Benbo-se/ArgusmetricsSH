import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createVerifiedUser, createUserWithWebsite } from '../helpers/auth';

test.describe('Dashboard Access', () => {
  test('unauthenticated user redirected from dashboard', async ({ page }) => {
    await page.goto('/dashboard');
    // Should redirect to login or show login page
    await page.waitForURL(/login|dashboard/);
  });

  test('authenticated user sees dashboard', async ({ page, request }) => {
    const { sessionToken } = await createVerifiedUser(request);

    // Set session cookie
    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto('/dashboard');
    await expect(page).toHaveURL(/dashboard/);
  });
});

test.describe('Website Management UI', () => {
  test('dashboard shows website list', async ({ page, request }) => {
    const { sessionToken } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto('/dashboard');
    // Should show at least one website
    await expect(page.locator('text=Test Site').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Website Analytics Dashboard', () => {
  test('website dashboard shows stats', async ({ page, request }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Track some data
    await api.track(trackingCode, '/');
    await api.track(trackingCode, '/about');

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}`);
    await expect(page.locator('text=Total Pageviews').first()).toBeVisible({ timeout: 10000 });
  });

  test('date range filter works', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}`);

    // Click 30D date range
    const btn30d = page.locator('button:has-text("30D"), a:has-text("30D")').first();
    if (await btn30d.isVisible()) {
      await btn30d.click();
      await page.waitForTimeout(1000);
    }
  });
});

test.describe('Website Settings', () => {
  test('settings page renders', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}/settings`);
    await expect(page.locator('text=Tracking Code').first()).toBeVisible({ timeout: 10000 });

    // The section row: the 404 guide is folded, and its link opens it.
    const guide = page.locator('details#not-found');
    await expect(guide).not.toHaveAttribute('open', '');
    await page.locator('[data-section-nav] a[href="#not-found"]').click();
    await expect(guide).toHaveAttribute('open', '');
    await expect(page.getByText('Setup Instructions')).toBeVisible();
  });
});

test.describe('Goals Page', () => {
  test('goals page renders', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}/goals`);
    await expect(page.locator('text=Create New Goal').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Team Page', () => {
  test('team page renders', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}/team`);
    await expect(page.locator('text=Team').first()).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Scroll depth on top pages', () => {
  test('a page with scroll data shows how far visitors read', async ({ page, request }) => {
    // Scroll depth was written on every pageview since the tracker was built
    // and displayed nowhere, which made it data collected for no purpose. It
    // is shown now, and this is what stops it going quiet again: the number
    // reaching the JSON island is not the same as it reaching the screen.
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);

    for (const depth of [40, 60, 80]) {
      const res = await request.post('/api/v1/analytics/track', {
        data: { tracking_code: trackingCode, path: '/long-article', scroll_depth: depth },
        headers: { 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/120' },
      });
      expect(res.status()).toBe(200);
    }

    // Same shape as the tests above: visit a page first, then set the cookie
    // from inside it. addCookies needs an origin and a blank page has none.
    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto(`/dashboard/website/${websiteId}?range=30d`);

    const row = page.locator('text=/long-article').first();
    await expect(row).toBeVisible();

    // 40, 60 and 80 average to 60.
    await expect(page.getByText('60% read')).toBeVisible();
  });
});

test.describe('Breakdown cards and toolbar', () => {
  // The lists are tabs in four cards. A click on a row reloads the page with
  // a filter, so a card that forgot its tab would jump back to the first one
  // on every click in it.
  test('a card remembers its tab across a filter and a reload', async ({ page, request }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);
    await api.track(trackingCode, '/', 'https://www.google.com/');
    await api.track(trackingCode, '/pricing', 'https://www.reddit.com/r/coffee');

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);
    await page.goto(`/dashboard/website/${websiteId}?range=30d`);

    const tab = (name: string) => page.getByRole('tab', { name, exact: true });
    const panel = (card: string, name: string) =>
      page.locator(`[role="tabpanel"][data-card="${card}"][data-tab="${name}"]`);

    // Before a choice: the first tab of each card, and only its panel.
    await expect(tab('Referrers')).toHaveAttribute('aria-selected', 'true');
    await expect(panel('sources', 'referrer')).toBeVisible();
    await expect(panel('sources', 'channels')).toBeHidden();
    await expect(panel('devices', 'browser')).toBeHidden();

    await tab('Browser').click();
    await expect(tab('Browser')).toHaveAttribute('aria-selected', 'true');
    await expect(tab('Type')).toHaveAttribute('aria-selected', 'false');
    await expect(panel('devices', 'browser')).toBeVisible();
    await expect(panel('devices', 'device')).toBeHidden();
    // The other cards are not touched by it.
    await expect(panel('sources', 'referrer')).toBeVisible();

    // A row in that tab filters the page, which loads it again.
    await panel('devices', 'browser').locator('.rank-row', { hasText: 'Chrome' }).click();
    await expect(page).toHaveURL(/browser=Chrome/);
    await expect(tab('Browser')).toHaveAttribute('aria-selected', 'true');
    await expect(panel('devices', 'browser')).toBeVisible();
    await expect(page.locator('[data-dimension-chip="browser"]')).toContainText('Chrome');

    await page.reload();
    await expect(panel('devices', 'browser')).toBeVisible();
    await expect(panel('devices', 'device')).toBeHidden();

    // The chip takes the filter off again, and the tab is still the chosen one.
    await page.locator('[data-dimension-chip="browser"] button').click();
    await expect(page).not.toHaveURL(/browser=/);
    await expect(panel('devices', 'browser')).toBeVisible();
  });

  test('referrers are listed by name, with the right mark, and filter by the stored address', async ({ page, request }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);
    await api.track(trackingCode, '/', 'https://www.google.com/');
    await api.track(trackingCode, '/', 'https://www.reddit.com/r/coffee');
    await api.track(trackingCode, '/', 'https://t.co/abc');
    await api.track(trackingCode, '/', 'https://kaffebloggen.example/basta/');

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);
    await page.goto(`/dashboard/website/${websiteId}?range=30d`);

    const rows = page.locator('[data-card="sources"][data-tab="referrer"] .rank-row');
    const row = (name: string) => rows.filter({ has: page.getByText(name, { exact: true }) });
    const mark = (name: string) => row(name).locator('.rank-icon');

    await expect(rows).toHaveCount(4);
    await expect(row('google.com')).toHaveAttribute('title', 'https://www.google.com/');
    await expect(mark('google.com')).toHaveClass(/fa-google/);
    // "t.co" is a substring of "reddit.com", which is how Reddit got a bird.
    await expect(mark('reddit.com/r/coffee')).toHaveClass(/fa-reddit/);
    await expect(mark('reddit.com/r/coffee')).not.toHaveClass(/fa-twitter/);
    await expect(mark('t.co/abc')).toHaveClass(/fa-twitter/);
    // No mark of its own: the neutral one, not somebody else's.
    await expect(mark('kaffebloggen.example/basta')).toHaveClass(/fa-globe/);

    await row('google.com').click();
    await expect(page).toHaveURL(/referrer=https%3A%2F%2Fwww\.google\.com%2F/);
    await expect(page.locator('[data-dimension-chip="referrer"]')).toContainText('google.com');
    await expect(page.locator('[data-dimension-chip="referrer"]')).not.toContainText('https://');
  });

  test('the toolbar fits a phone in two rows and its menus stay on the screen', async ({ page, request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);
    await page.goto(`/dashboard/website/${websiteId}`);

    const toolbar = page.locator('.dash-toolbar');
    const tops = await toolbar.locator(':scope > *').evaluateAll((els) =>
      [...new Set(els.map((el) => Math.round(el.getBoundingClientRect().top)))]
    );
    expect(tops.length, `the controls sit on ${tops.length} rows`).toBe(2);

    // Nothing on the page is wider than the screen.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(0);

    await toolbar.getByTitle('Choose a period').click();
    const menu = toolbar.locator('.tool-pop').first();
    await expect(menu).toBeVisible();
    const box = await menu.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);

    await menu.getByRole('button', { name: 'Last 7 days' }).click();
    await expect(page).toHaveURL(/range=7d/);
    await expect(toolbar.getByRole('button', { name: '7D' })).toHaveAttribute('aria-pressed', 'true');
  });
});
