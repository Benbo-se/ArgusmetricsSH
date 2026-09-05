import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * The tracker must not count the developer's own machine.
 *
 * It used to, and it showed up as referrals: `http://localhost:8202/` in Top
 * Referrers next to Bing. On a site with thirteen pageviews, four of them the
 * developer's, a third of the statistics was noise, and it hurts the newest
 * sites hardest.
 *
 * Checked in a browser, on a page actually served from localhost, because
 * that is the only place the check runs.
 */
test.describe('Local development is not counted', () => {
  test('a page served from localhost sends nothing', async ({ page, request }) => {
    const { trackingCode } = await createUserWithWebsite(request);

    const sent: string[] = [];
    await page.route('**/api/v1/analytics/**', route => {
      sent.push(route.request().url());
      return route.fulfill({ status: 200, body: '{"success":true}' });
    });

    await page.goto(`/static/tracker.min.js`);           // same origin, localhost
    await page.setContent(`<html><body>hello</body></html>`);
    await page.addScriptTag({
      url: '/static/tracker.min.js',
      // Playwright cannot set data-* on addScriptTag, so set it up by hand.
    }).catch(() => {});

    await page.evaluate((code) => {
      const s = document.createElement('script');
      s.src = '/static/tracker.min.js';
      s.setAttribute('data-tracking-code', code);
      document.head.appendChild(s);
    }, trackingCode);

    await page.waitForTimeout(1500);
    console.log('SKICKAT_FRAN_LOCALHOST=' + sent.length);
    expect(sent, `the tracker sent ${sent.length} request(s) from localhost`).toEqual([]);
  });

  test('the override still lets you test the tracker itself', async ({ page, request }) => {
    const { trackingCode } = await createUserWithWebsite(request);

    const sent: string[] = [];
    await page.route('**/api/v1/analytics/**', route => {
      sent.push(route.request().url());
      return route.fulfill({ status: 200, body: '{"success":true}' });
    });

    await page.goto('/login');
    await page.setContent('<html><body>hello</body></html>');
    await page.evaluate((code) => {
      const s = document.createElement('script');
      s.src = '/static/tracker.min.js';
      s.setAttribute('data-tracking-code', code);
      s.setAttribute('data-track-localhost', 'true');
      document.head.appendChild(s);
    }, trackingCode);

    await page.waitForTimeout(1500);
    console.log('SKICKAT_MED_OVERRIDE=' + sent.length);
    sent.forEach((u,i)=>console.log('URL'+i+'='+u.split('/api/v1/')[1]));
    expect(sent.length, 'the override did not re-enable tracking').toBeGreaterThan(0);
  });
});
