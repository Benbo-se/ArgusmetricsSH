import { test, expect } from '@playwright/test';

/**
 * The tracker must be silent in a customer's console.
 *
 * It was not. Every page load of every site running it threw:
 *
 *     Uncaught ReferenceError: checkScrollMilestones is not defined
 *
 * recordScrollDepth had that name back when it fired an event at 25, 50, 75
 * and 100 per cent. The rename missed one caller inside a setTimeout, and a
 * free variable in JavaScript is only resolved when it is reached, so the
 * build was clean, the minifier was right not to touch a name it could not
 * resolve, and CI's check that the artifact matched the source passed. It had
 * to reach a real browser to be noticed, and the browser that noticed was a
 * customer's, whose own end-to-end suite asserts zero console errors.
 *
 * There is a static check now (frontend/tracking-script/check-globals.js) that
 * would have caught this one at build time. This test is the other half: it
 * runs the real artifact in a real engine, so it catches the failures a parser
 * cannot see, and it is the shape of the check that actually found the bug.
 *
 * Errors are collected from both channels deliberately. An uncaught throw from
 * a timer callback arrives as 'pageerror', not as a console message, which is
 * exactly how this one behaved.
 */

/** Everything the page complained about, from both channels. */
function collectProblems(page: import('@playwright/test').Page): string[] {
    const problems: string[] = [];
    page.on('console', message => {
        if (message.type() === 'error') problems.push(`console: ${message.text()}`);
    });
    page.on('pageerror', error => problems.push(`pageerror: ${error.message}`));
    return problems;
}

/** A page that loads the tracker exactly as a customer's site does. */
async function pageWithTracker(page: import('@playwright/test').Page, baseURL: string) {
    // The endpoints are stubbed: this is about whether the script runs, not
    // about what it sends, and a real request would be refused for an
    // unverified domain anyway.
    await page.route('**/api/v1/analytics/**', route =>
        route.fulfill({ status: 200, body: '{"success":true}' }));

    await page.setContent(`
        <!doctype html>
        <html><head><title>Customer site</title></head>
        <body>
            <h1>A page</h1>
            <div style="height: 4000px">Tall enough that scroll depth is measurable.</div>
            <a href="https://example.com/elsewhere">An outbound link</a>
            <a href="/handbook.pdf" download>A download</a>
            <script src="${baseURL}/static/tracker.min.js"
                    data-tracking-code="console-check"
                    data-track-localhost="true"></script>
        </body></html>
    `, { waitUntil: 'load' });
}

test.describe('The tracker is silent in the console', () => {
    test('a page load produces no errors at all', async ({ page, baseURL }) => {
        const problems = collectProblems(page);

        await pageWithTracker(page, baseURL!);

        // The initial scroll reading is on a 100ms timer, and that timer is
        // where the ReferenceError came from. A test that does not wait for it
        // passes against the broken build.
        await page.waitForTimeout(600);

        expect(problems, problems.join('\n')).toEqual([]);
    });

    test('scrolling produces no errors either', async ({ page, baseURL }) => {
        const problems = collectProblems(page);

        await pageWithTracker(page, baseURL!);
        await page.evaluate(() => window.scrollTo(0, 2000));
        await page.waitForTimeout(400);
        await page.evaluate(() => window.scrollTo(0, 3800));
        await page.waitForTimeout(400);

        expect(problems, problems.join('\n')).toEqual([]);
    });

    test('the public interface is actually there', async ({ page, baseURL }) => {
        /**
         * Guards the two tests above against passing for the wrong reason. A
         * script that fails to load at all is also perfectly quiet.
         */
        await pageWithTracker(page, baseURL!);

        const api = await page.evaluate(() => Object.keys((window as any).argus || {}));

        expect(api).toContain('track');
        expect(api).toContain('trackEvent');
        expect(api).toContain('trackEcommerce');
    });

    test('the initial reading happens without scrolling', async ({ page, baseURL }) => {
        /**
         * The bug was not only noise. That timer takes the first measurement,
         * for a page that is already scrolled when it loads: an anchor link, a
         * restored position on back navigation. While it threw, a visitor who
         * landed halfway down and read without scrolling reported no depth at
         * all, and the dashboard's scroll figures were quietly missing them.
         */
        // Observed rather than intercepted, for two reasons. pageWithTracker
        // registers its own catch-all and Playwright lets the last route
        // registered win, so a second route for the same paths never runs. And
        // the depth goes out through sendBeacon, which a request listener sees
        // and a narrower route may not.
        let depthSent: number | null = null;
        page.on('request', request => {
            if (!request.url().includes('/track-scroll')) return;
            depthSent = JSON.parse(request.postData() || '{}').depth ?? null;
        });

        await pageWithTracker(page, baseURL!);
        await page.evaluate(() => window.scrollTo(0, 2000));
        await page.waitForTimeout(400);

        // Leaving is what sends it.
        await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
        await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
        await page.waitForTimeout(300);

        expect(depthSent).not.toBeNull();
        expect(depthSent!).toBeGreaterThan(0);
    });
});
