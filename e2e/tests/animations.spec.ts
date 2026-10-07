import { test, expect, Page } from '@playwright/test';

/**
 * The animations on the marketing site (site/static/js/anim.js).
 *
 * The engine exposes __anRender(t) on each scene so a frame can be checked
 * directly instead of waited for. The play test does wait, because that is
 * the part a seek cannot prove: that the clock actually runs.
 */

const SCENES = 4;

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
