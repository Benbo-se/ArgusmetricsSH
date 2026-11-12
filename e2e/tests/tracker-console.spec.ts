import { readFileSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
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

/** A person's user agent. Headless Chromium says "HeadlessChrome", which the
 *  tracker refuses (#103), so the page presents this one instead. */
const PERSON_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36';

/** A page that loads the tracker exactly as a customer's site does. */
async function pageWithTracker(page: import('@playwright/test').Page, baseURL: string,
                               { trackLocalhost = true, doNotTrack = false, asPerson = true, userAgent = '' } = {}) {
    // Playwright's browser reports navigator.webdriver and a HeadlessChrome
    // user agent, and the tracker now refuses both (#103). The page acts as a
    // person unless a test asks otherwise, so the DNT and localhost tests
    // below are refused for their own reason and not for this one.
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
            ${doNotTrack ? `<script>Object.defineProperty(navigator, 'doNotTrack', { get: () => '1' });</script>` : ''}
            ${asPerson ? `<script>Object.defineProperty(navigator, 'webdriver', { get: () => false });</script>` : ''}
            <script>Object.defineProperty(navigator, 'userAgent', { get: () => ${JSON.stringify(userAgent || PERSON_UA)} });</script>
            <script src="${baseURL}/static/tracker.min.js"
                    data-tracking-code="console-check"
                    ${trackLocalhost ? 'data-track-localhost="true"' : ''}></script>
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

    /**
     * #106. Pageviews and events checked Do Not Track and local development;
     * the scroll report checked neither. A visitor who had asked not to be
     * tracked sent no pageview and then, on leaving, sent the path and how far
     * they read. Both tests below go through exactly the flow the test above
     * proves does send, so they cannot pass by nothing ever being sent.
     */
    async function scrollAndLeave(page: import('@playwright/test').Page) {
        await page.evaluate(() => window.scrollTo(0, 2000));
        await page.waitForTimeout(400);
        await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
        await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
        await page.waitForTimeout(300);
    }

    test('Do Not Track also stops the scroll report', async ({ page, baseURL }) => {
        const sent: string[] = [];
        page.on('request', request => {
            if (request.url().includes('/api/v1/analytics/')) sent.push(request.url());
        });

        // Set inside the page, before the tracker, rather than with an init
        // script: an init script only runs on navigation, and navigating to
        // about:blank first left a page that sent nothing at all, so the test
        // passed against the unfixed tracker too.
        await pageWithTracker(page, baseURL!, { doNotTrack: true });
        await scrollAndLeave(page);

        expect(sent, `sent with Do Not Track on:\n${sent.join('\n')}`).toEqual([]);
    });

    test('a local page sends no scroll report either', async ({ page, baseURL }) => {
        const sent: string[] = [];
        page.on('request', request => {
            if (request.url().includes('/api/v1/analytics/')) sent.push(request.url());
        });

        // setContent leaves the page on about:blank, which has no hostname and
        // therefore counts as local, the same as file://.
        await pageWithTracker(page, baseURL!, { trackLocalhost: false });
        await scrollAndLeave(page);

        expect(sent, `sent from a local page:\n${sent.join('\n')}`).toEqual([]);
    });

    /**
     * #103. Crawlers that run JavaScript ran the tracker: Meta's alone sent
     * about 175,000 pageviews to one instance in nine days. Each test goes
     * through the flow that sends a pageview and a scroll report for a person.
     */
    test('an automated browser sends nothing', async ({ page, baseURL }) => {
        const sent: string[] = [];
        page.on('request', r => { if (r.url().includes('/api/v1/analytics/')) sent.push(r.url()); });

        await pageWithTracker(page, baseURL!, { asPerson: false });
        await scrollAndLeave(page);

        expect(sent, sent.join('\n')).toEqual([]);
    });

    test('a crawler user agent sends nothing', async ({ page, baseURL }) => {
        const sent: string[] = [];
        page.on('request', r => { if (r.url().includes('/api/v1/analytics/')) sent.push(r.url()); });

        await pageWithTracker(page, baseURL!, {
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36 (compatible; meta-externalagent/1.1)',
        });
        await scrollAndLeave(page);

        expect(sent, sent.join('\n')).toEqual([]);
    });

    /**
     * #109. Google Tag Manager loads the tracker with injectScript, which
     * cannot put data attributes on the tag, so its template passes the
     * settings in window.argusConfig. The tracker used to ignore that, start
     * without a tracking code, and send nothing.
     */
    test('settings from window.argusConfig work, as GTM passes them', async ({ page, baseURL }) => {
        const bodies: any[] = [];
        page.on('request', r => {
            if (r.url().endsWith('/api/v1/analytics/track')) bodies.push(JSON.parse(r.postData() || '{}'));
        });
        await page.route('**/api/v1/analytics/**', route =>
            route.fulfill({ status: 200, body: '{"success":true}' }));

        await page.setContent(`
            <!doctype html><html><head><title>GTM site</title></head><body>
            <script>
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'userAgent', { get: () => ${JSON.stringify(PERSON_UA)} });
                window.argusConfig = {
                    trackingCode: 'gtmcode1',
                    apiEndpoint: '${baseURL}/api/v1/analytics/track',
                    trackLocalhost: true
                };
            </script>
            <script src="${baseURL}/static/tracker.min.js"></script>
            </body></html>`, { waitUntil: 'load' });
        await page.waitForTimeout(500);

        expect(bodies.length, 'no pageview was sent').toBe(1);
        expect(bodies[0].tracking_code).toBe('gtmcode1');
    });

    test('trackEvent called from another script keeps the tracking code', async ({ page, baseURL }) => {
        // document.currentScript is the calling script during a synchronous
        // call, so reading the code from it lost the code.
        const events: any[] = [];
        page.on('request', r => {
            if (r.url().endsWith('/track-event')) events.push(JSON.parse(r.postData() || '{}'));
        });
        await pageWithTracker(page, baseURL!);
        await page.addScriptTag({ content: "argus.trackEvent('clicked_cta')" });
        await page.waitForTimeout(400);

        expect(events.map(e => e.tracking_code)).toEqual(['console-check']);
    });

    /**
     * #107. In a single-page app the report of how far /old was read went out
     * after the URL had already changed, and arrived as the depth of /new.
     * Both ways of leaving: pushState, and the back button (popstate), where
     * the URL has changed before any script runs.
     */
    test('a depth is reported for the page it was read on, in a single-page app', async ({ page }) => {
        // The tracker is served from the same made-up origin: Chrome refuses a
        // public-looking page loading a script from 127.0.0.1 (Private Network
        // Access), which has nothing to do with what is tested here.
        const trackerJs = readFileSync('../backend/app/static/tracker.min.js', 'utf8');
        await page.route('http://shop.test/tracker.min.js', route =>
            route.fulfill({ contentType: 'application/javascript', body: trackerJs }));
        await page.route('http://shop.test/api/**', route =>
            route.fulfill({ status: 200, body: '{"success":true}' }));
        await page.route(/^http:\/\/shop\.test\/(old|new)$/, route => route.fulfill({
            contentType: 'text/html',
            body: `<!doctype html><html><body>
                <div style="height: 4000px">Tall enough to scroll.</div>
                <script>
                    Object.defineProperty(navigator, 'webdriver', { get: () => false });
                    Object.defineProperty(navigator, 'userAgent', { get: () => ${JSON.stringify(PERSON_UA)} });
                </script>
                <script src="/tracker.min.js" data-tracking-code="spa-check"
                        data-api-endpoint="http://shop.test/api/v1/analytics/track" data-track-localhost="true"></script>
            </body></html>`,
        }));
        const depths: { path: string, depth: number }[] = [];
        page.on('request', r => {
            if (r.url().includes('/track-scroll')) depths.push(JSON.parse(r.postData() || '{}'));
        });

        await page.goto('http://shop.test/old');
        await page.evaluate(() => window.scrollTo(0, 2000));
        await page.waitForTimeout(400);
        await page.evaluate(() => history.pushState({}, '', '/new'));
        await page.waitForTimeout(300);

        expect(depths.map(d => d.path), 'pushState').toEqual(['/old']);

        await page.evaluate(() => window.scrollTo(0, 3500));
        await page.waitForTimeout(400);
        await page.goBack();
        await page.waitForTimeout(300);

        expect(depths.map(d => d.path), 'back button').toEqual(['/old', '/new']);
    });
});

/**
 * A customer's site and the instance are different origins, which is the only
 * way the tracker is ever used and the one thing the tests above, served from
 * the instance itself, never exercised (#166).
 *
 * Two real HTTP servers on two ports, because a page and an API on different
 * ports are different origins and the browser applies its real CORS rules.
 * Routed (stubbed) responses did not: Playwright's fulfilled preflight was let
 * through for a credentialed beacon, and the test passed against the broken
 * tracker. The "instance" answers as the real one does for these endpoints:
 * Access-Control-Allow-Origin: * and no Allow-Credentials. A POST only counts
 * as received if it got past the preflight, so a report that dies in the CORS
 * check never lands in the lists below.
 */
test.describe('The tracker on a site that is not the instance', () => {
    const CORS = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': '*',
        'Access-Control-Allow-Headers': '*',
    };
    const trackerJs = readFileSync('../backend/app/static/tracker.min.js', 'utf8');

    let pageviews: any[] = [];
    let depths: any[] = [];
    let instance: Server;
    let site: Server;
    let instanceUrl = '';
    let siteUrl = '';

    function listen(server: Server): Promise<string> {
        return new Promise(resolve => server.listen(0, '127.0.0.1', () =>
            resolve(`http://127.0.0.1:${(server.address() as AddressInfo).port}`)));
    }

    test.beforeAll(async () => {
        instance = createServer((req, res) => {
            if (req.method === 'OPTIONS') {
                res.writeHead(204, CORS).end();
                return;
            }
            let raw = '';
            req.on('data', chunk => raw += chunk);
            req.on('end', () => {
                const body = JSON.parse(raw || '{}');
                if (req.url!.endsWith('/track')) pageviews.push(body);
                if (req.url!.endsWith('/track-scroll')) depths.push(body);
                res.writeHead(200, { ...CORS, 'Content-Type': 'application/json' }).end('{"success":true}');
            });
        });
        instanceUrl = await listen(instance);

        site = createServer((req, res) => {
            if (req.url === '/tracker.min.js') {
                res.writeHead(200, { 'Content-Type': 'application/javascript' }).end(trackerJs);
                return;
            }
            res.writeHead(200, { 'Content-Type': 'text/html' }).end(`<!doctype html><html><body>
                <div style="height: 4000px">Tall enough to scroll.</div>
                <script>
                    Object.defineProperty(navigator, 'webdriver', { get: () => false });
                    Object.defineProperty(navigator, 'userAgent', { get: () => ${JSON.stringify(PERSON_UA)} });
                </script>
                <script src="/tracker.min.js" data-tracking-code="cors-check"
                        data-api-endpoint="${instanceUrl}/api/v1/analytics/track" data-track-localhost="true"></script>
            </body></html>`);
        });
        siteUrl = await listen(site);
    });

    test.afterAll(() => {
        instance.close();
        site.close();
    });

    test.beforeEach(() => {
        pageviews = [];
        depths = [];
    });

    async function open(page: import('@playwright/test').Page, referer?: string) {
        await page.goto(`${siteUrl}/a`, referer ? { referer } : {});
        await page.waitForTimeout(300);
    }

    async function leave(page: import('@playwright/test').Page) {
        await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
        await page.waitForTimeout(300);
    }

    test('the scroll depth arrives (#166)', async ({ page }) => {
        await open(page);
        await page.evaluate(() => window.scrollTo(0, 2000));
        await page.waitForTimeout(400);
        await leave(page);

        expect(pageviews.length, 'the pageview, as a control that the servers are reachable').toBe(1);
        expect(depths.length, 'no scroll report reached the server').toBe(1);
        expect(depths[0].path).toBe('/a');
        expect(depths[0].depth).toBeGreaterThan(0);
    });

    test('the depth is reported again once it has grown (#167)', async ({ page }) => {
        await open(page);
        await page.evaluate(() => window.scrollTo(0, 800));
        await page.waitForTimeout(400);
        await leave(page);
        await leave(page); // nothing new since: must not send again
        await page.evaluate(() => window.scrollTo(0, 3800));
        await page.waitForTimeout(400);
        await leave(page);

        expect(depths.length, JSON.stringify(depths)).toBe(2);
        expect(depths[1].depth).toBeGreaterThan(depths[0].depth);
        expect(depths[1].depth).toBeGreaterThan(90);
    });

    test('replaceState on the same path is not a new pageview (#177)', async ({ page }) => {
        await open(page);
        expect(pageviews.length, 'the first pageview').toBe(1);

        await page.evaluate(() => history.replaceState({ scrollY: 120 }, ''));
        await page.waitForTimeout(300);
        expect(pageviews.length, 'replaceState on the same path').toBe(1);

        await page.evaluate(() => history.replaceState({}, '', '/c'));
        await page.waitForTimeout(300);
        expect(pageviews.map(p => p.path), 'replaceState to another path').toEqual(['/a', '/c']);
    });

    test('the referrer is sent on the first pageview only (#177)', async ({ page }) => {
        await open(page, 'https://www.google.com/search?q=x');
        await page.evaluate(() => history.pushState({}, '', '/b'));
        await page.waitForTimeout(300);
        await page.evaluate(() => history.pushState({}, '', '/c'));
        await page.waitForTimeout(300);

        expect(pageviews.map(p => p.path)).toEqual(['/a', '/b', '/c']);
        expect(pageviews.map(p => p.referrer)).toEqual(['https://www.google.com/search', null, null]);
    });
});
