import { test, expect, Page } from '@playwright/test';

/**
 * The animations on the marketing site (site/static/js/anim.js).
 *
 * The engine exposes __anRender(t) on each scene so a frame can be checked
 * directly instead of waited for. The play test does wait, because that is
 * the part a seek cannot prove: that the clock actually runs.
 */

const SCENES = 6;  // snippet, size, goal, banner, ip, terminal

async function scenes(page: Page) {
  return page.locator('.an-wrap');
}

async function frame(page: Page, index: number, t: number) {
  await page.evaluate(([i, s]) => {
    const w = document.querySelectorAll('.an-wrap')[i] as any;
    w.__anRender(s);
  }, [index, t]);
}

test('all four scenes start, with nothing in the console', async ({ page }) => {
  const problems: string[] = [];
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') problems.push(m.text()); });
  page.on('pageerror', e => problems.push(e.message));

  await page.goto('/');
  const wraps = await scenes(page);
  await expect(wraps).toHaveCount(SCENES);
  for (let i = 0; i < SCENES; i++) {
    await expect(wraps.nth(i)).toHaveClass(/an-js/);
  }
  expect(problems, problems.join('\n')).toEqual([]);
});

test('a scene in view plays, and its clock moves', async ({ page }) => {
  await page.goto('/');
  const first = (await scenes(page)).first();
  await first.scrollIntoViewIfNeeded();
  await page.waitForTimeout(1500);

  const t = await first.evaluate((w: any) => w.__anT);
  expect(t, 'the clock never started').toBeGreaterThan(.5);
  await expect(first.locator('.an-cap.an-on')).toHaveCount(1);
});

test('the frames show what the copy says', async ({ page }) => {
  await page.goto('/');
  const wraps = await scenes(page);

  // Snippet: after the second burst, three visitors and 131 pageviews.
  await frame(page, 0, 11);
  await expect(wraps.nth(0).locator('.as-tile .v').first()).toHaveText('3');
  await expect(wraps.nth(0).locator('.as-tile .v').nth(1)).toHaveText('131');

  // IP: by the end the address is marked not stored and midnight has come.
  const ip = wraps.filter({ hasText: '81.224.17.42' });
  await ip.evaluate((w: any) => w.__anRender(15));
  await expect(ip.locator('.nope')).toHaveText('not stored');
  await expect(ip.locator('.ai-night')).toHaveClass(/an-on/);
});

test('prefers-reduced-motion gets one still frame and no clock', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const first = (await scenes(page)).first();
  await first.scrollIntoViewIfNeeded();
  await page.waitForTimeout(1200);

  expect(await first.evaluate((w: any) => w.__anT), 'the scene is playing').toBeUndefined();
  // The still frame is a finished one, not an empty canvas at t=0.
  await expect(first.locator('.as-tile .v').first()).toHaveText('3');
});

test('a phone gets the phone layout', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const wraps = await scenes(page);
  for (let i = 0; i < SCENES; i++) {
    await expect(wraps.nth(i)).toHaveClass(/an-m/);
  }
});


test('the size scene ends on the measured numbers, to scale', async ({ page }) => {
  await page.goto('/');
  const size = page.locator('.ax-wrap');
  await size.evaluate((w: any) => w.__anRender(6));
  await expect(size.locator('.ax-r1 .ax-num b')).toHaveText('155');
  await expect(size.locator('.ax-us')).toHaveClass(/an-on/);
  const widths = await size.evaluate((w) => ['.ax-ga', '.ax-us'].map(
    (s) => (w.querySelector(s) as HTMLElement).style.width));
  expect(widths).toEqual(['100%', '1.85%'])
});

test('the terminal ends healthy, and its copy button has the real commands', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/');
  const term = page.locator('.at-wrap');
  await term.evaluate((w: any) => w.__anRender(13));
  await expect(term).toContainText('"healthy"');
  await expect(term).toContainText('SECRET_KEY');

  await page.getByRole('button', { name: /Copy these commands/ }).click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain('cp .env.example .env');
  expect(copied).toContain('docker compose up -d postgres backend');
});

test('feature cards rise into view, and are all there without motion', async ({ page }) => {
  await page.goto('/');
  const card = page.locator('#features [data-reveal]').first();
  await card.scrollIntoViewIfNeeded();
  await expect(card).toHaveClass(/rv-in/);

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  // Nothing hidden: the page never opted in to hiding them.
  expect(await page.evaluate(() => document.documentElement.classList.contains('rv-on'))).toBe(false);
});

test('the docs build a snippet from what you type', async ({ page }) => {
  await page.goto('/docs/');
  await page.getByLabel('Your Argusmetrics address').fill('stats.example.com/');
  await page.getByLabel('Tracking code, from your dashboard').fill('k3x9q2ab');
  await page.getByLabel('Count localhost too, while testing').check();
  const code = page.locator('code', { hasText: 'data-tracking-code' }).first();
  await expect(code).toContainText('data-tracking-code="k3x9q2ab"');
  await expect(code).toContainText('data-track-localhost="true"');
  // The scheme is added and the trailing slash dropped.
  await expect(code).toContainText('src="https://stats.example.com/static/tracker.min.js"');
});

for (const [path, count] of [['/compare/google-analytics', 3], ['/compare/plausible', 1], ['/compare/matomo', 1]] as const) {
  test(`${path} carries its scenes and starts them`, async ({ page }) => {
    await page.goto(path);
    const wraps = page.locator('.an-wrap');
    await expect(wraps).toHaveCount(count);
    await expect(wraps.first()).toHaveClass(/an-js/);
  });
}

test('a hidden tab shows each scene finished, not its empty first frame', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(document, 'hidden', { get: () => true });
    Object.defineProperty(document, 'visibilityState', { get: () => 'hidden' });
  });
  await page.goto('/');
  await expect(page.locator('.an-wrap').first().locator('.as-tile .v').first()).toHaveText('3');
});
