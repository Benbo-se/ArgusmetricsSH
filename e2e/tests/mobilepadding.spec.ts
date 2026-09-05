import { test, expect } from '@playwright/test';

const PAGES = ['/', '/data.html', '/about.html', '/privacy.html', '/terms.html',
               '/changelog.html', '/docs/', '/compare/plausible.html',
               '/compare/matomo.html', '/compare/google-analytics.html'];

test('nothing overflows the viewport on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const problems: string[] = [];

  for (const path of PAGES) {
    const res = await page.goto(path).catch(() => null);
    if (!res || res.status() >= 400) { console.log('HOPPAR=' + path); continue; }

    const found = await page.evaluate(() => {
      const w = document.documentElement.clientWidth;
      const out: string[] = [];

      // An element wider than the viewport is fine if something above it
      // scrolls: that is a table in its own box, which is the fix, not the
      // bug. Only unclipped overflow moves the page.
      const insideAScroller = (el: Element) => {
        let p = el.parentElement;
        while (p) {
          const ox = getComputedStyle(p).overflowX;
          if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return true;
          p = p.parentElement;
        }
        return false;
      };

      document.querySelectorAll<HTMLElement>('body *').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || (r.right <= w + 1 && r.left >= -1)) return;
        if (insideAScroller(el)) return;
        const text = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
        out.push(`${el.tagName.toLowerCase()} w=${Math.round(r.width)} :: ${text}`);
      });
      return { scrollW: document.documentElement.scrollWidth, clientW: w, out: out.slice(0, 3) };
    });

    if (found.scrollW > found.clientW + 1 || found.out.length) {
      problems.push(`${path}  scroll=${found.scrollW} viewport=${found.clientW}  ${found.out.join(' | ')}`);
    }
  }
  expect(
    problems,
    'these pages scroll sideways on a 375px phone, which reads as broken ' +
      'padding. Wide content belongs in its own overflow-x-auto box, and a ' +
      'grid column needs min-w-0 or it refuses to shrink below its content:\n  ' +
      problems.join('\n  ')
  ).toEqual([]);
});
