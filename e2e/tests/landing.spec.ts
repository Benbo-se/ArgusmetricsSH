import { test, expect } from '@playwright/test';

test.describe('Landing Page', () => {
  test('page loads with title', async ({ page }) => {
    await page.goto('/');
    const title = await page.title();
    expect(title).toBeTruthy();
  });

  test('navigation bar is visible', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('nav').first()).toBeVisible();
  });

  test('login/signup links exist', async ({ page }) => {
    await page.goto('/');
    const loginLink = page.locator('a[href*="login"]').first();
    await expect(loginLink).toBeVisible();
  });

  test('hero section is visible', async ({ page }) => {
    await page.goto('/');
    // Hero section should have heading and CTA
    const heading = page.locator('h1').first();
    await expect(heading).toBeVisible();
  });
});

test.describe('About Page', () => {
  test('about page loads', async ({ page }) => {
    await page.goto('/about');
    expect(await page.title()).toBeTruthy();
  });
});

test.describe('Contact Page', () => {
  test('contact page loads with email', async ({ page }) => {
    await page.goto('/contact');
    await expect(page.locator('text=reda@argusmetrics').first()).toBeVisible();
  });
});

test.describe('Privacy Page', () => {
  test('privacy page loads', async ({ page }) => {
    await page.goto('/privacy');
    await expect(page.locator('h1').first()).toBeVisible();
  });
});

test.describe('Terms Page', () => {
  test('terms page loads', async ({ page }) => {
    await page.goto('/terms');
    await expect(page.locator('text=Terms').first()).toBeVisible();
  });
});

test.describe('Docs Page', () => {
  test('docs page loads', async ({ page }) => {
    await page.goto('/docs');
    expect(await page.title()).toBeTruthy();
  });
});

test.describe('SEO', () => {
  test('robots.txt is accessible', async ({ request }) => {
    const res = await request.get('/robots.txt');
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toContain('User-agent');
  });

  test('sitemap.xml is accessible', async ({ request }) => {
    const res = await request.get('/sitemap.xml');
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toContain('urlset');
  });
});
