import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * The dashboard runs Alpine's CSP build, and its failure mode is silence.
 *
 * An expression that build cannot evaluate does not throw. It writes a warning
 * to the console and renders nothing, so the page loads, looks nearly right,
 * and a dropdown quietly does not open. Every other test in this suite would
 * pass through that.
 *
 * So these read the browser console, which is the only place the failure
 * appears, and also check that the policy the browser enforced is the one
 * without 'unsafe-eval'. A CSP violation is reported the same way: a console
 * message and nothing else.
 */

const PAGES = [
  { name: 'website list', path: '/dashboard' },
  { name: 'website dashboard', path: (id: number) => `/dashboard/website/${id}` },
  { name: 'settings', path: (id: number) => `/dashboard/website/${id}/settings` },
  { name: 'goals', path: (id: number) => `/dashboard/website/${id}/goals` },
  { name: 'funnels', path: (id: number) => `/dashboard/website/${id}/funnels` },
  { name: 'team', path: (id: number) => `/dashboard/website/${id}/team` },
  { name: 'revenue', path: (id: number) => `/dashboard/website/${id}/revenue` },
  { name: 'debug console', path: (id: number) => `/dashboard/website/${id}/debug` },
];

test.describe('Content-Security-Policy', () => {
  test('no page reports an Alpine or CSP problem to the console', async ({
    page,
    request,
  }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    const complaints: string[] = [];
    page.on('console', (message) => {
      const text = message.text();
      if (
        // Warnings too, not only errors. Alpine says "Alpine Warning: x-for
        // key cannot be an object" and carries on, and that one slipped
        // through this very check while it only looked for "Alpine Error".
        text.includes('Alpine Error') ||
        text.includes('Alpine Warning') ||
        text.includes('unable to interpret') ||
        text.includes('Content Security Policy') ||
        text.includes('Refused to evaluate') ||
        text.includes('Refused to execute')
      ) {
        complaints.push(`${page.url()}: ${text}`);
      }
    });
    page.on('pageerror', (error) => {
      complaints.push(`${page.url()}: ${error.message}`);
    });

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    for (const entry of PAGES) {
      const path =
        typeof entry.path === 'function' ? entry.path(websiteId) : entry.path;
      await page.goto(path);
      // Alpine initialises on DOMContentLoaded; give it a moment to complain.
      await page.waitForTimeout(300);
    }

    expect(
      complaints,
      `Alpine or the CSP objected. Every one of these is a control that looks ` +
        `present and does nothing:\n  ${complaints.join('\n  ')}`
    ).toEqual([]);
  });

  test('the served policy allows no unsafe script source', async ({ page }) => {
    const response = await page.goto('/login');
    const policy = response?.headers()['content-security-policy'] ?? '';

    expect(policy).not.toContain('unsafe-eval');
    expect(policy.split('style-src')[0]).not.toContain('unsafe-inline');
    expect(policy).toContain("script-src 'self' 'nonce-");
  });

  test('a dropdown actually opens', async ({ page, request }) => {
    /**
     * One real interaction, because "no console errors" and "the thing works"
     * are not the same claim. The Add Website modal is driven by the shared
     * disclosure component, so if the CSP build cannot reach it, nothing in
     * the dashboard can be reached either.
     */
    const { sessionToken } = await createUserWithWebsite(request);

    await page.goto('/login');
    await page.evaluate((token) => {
      document.cookie = `session_token=${token}; path=/`;
    }, sessionToken);

    await page.goto('/dashboard');

    const modal = page.locator('text=Add Website').last();
    await page.getByRole('button', { name: 'Add Website' }).first().click();
    await expect(modal).toBeVisible({ timeout: 5000 });
  });
});
