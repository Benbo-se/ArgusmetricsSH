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
      document.querySelectorAll<HTMLElement>('body *').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0) return;
        if (r.right > w + 1 || r.left < -1) {
          const id = el.tagName.toLowerCase() +
            (el.className && typeof el.className === 'string'
              ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
          out.push(`${id} left=${Math.round(r.left)} right=${Math.round(r.right)}`);
        }
      });
      return { scrollW: document.documentElement.scrollWidth, clientW: w, out: out.slice(0, 4) };
    });

    if (found.scrollW > found.clientW + 1 || found.out.length) {
      problems.push(`${path}  scroll=${found.scrollW} viewport=${found.clientW}  ${found.out.join(' | ')}`);
    }
  }
  problems.forEach(p => console.log('OVERFLOW=' + p));
  console.log('ANTAL_SIDOR_MED_PROBLEM=' + problems.length);
});
