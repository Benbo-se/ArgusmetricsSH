import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createUserWithWebsite } from '../helpers/auth';

test.describe('Public Dashboard', () => {
  test('enable public dashboard and access it', async ({ request, page }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Track some data first
    await api.track(trackingCode, '/');
    await api.track(trackingCode, '/about');

    // Enable public access
    const publicRes = await request.put(`/api/v1/websites/${websiteId}/public-access`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { is_public: true },
    });
    expect(publicRes.status()).toBe(200);
    const body = await publicRes.json();
    expect(body.is_public).toBe(true);

    // Get the share token
    const websiteRes = await api.getWebsite(sessionToken, websiteId);
    const shareToken = websiteRes.body.public_share_token;
    expect(shareToken).toBeTruthy();

    // Access public dashboard (no auth)
    const response = await page.goto(`/public/${shareToken}`);
    expect(response?.status()).toBe(200);
  });

  // The shared page is the owner's page without anything that acts. Its
  // controls are Alpine's too, and Alpine's CSP build fails in silence, so
  // this reads the console as csp.spec.ts does for the pages behind the login.
  test('the cards switch tabs, the rows do nothing, and the console stays clean', async ({ request, page }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);
    await api.track(trackingCode, '/', 'https://www.google.com/');
    await api.track(trackingCode, '/pricing', 'https://www.reddit.com/r/coffee');
    await request.put(`/api/v1/websites/${websiteId}/public-access`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { is_public: true },
    });
    const shareToken = (await api.getWebsite(sessionToken, websiteId)).body.public_share_token;

    const complaints: string[] = [];
    page.on('console', (message) => {
      if (['warning', 'error'].includes(message.type())) complaints.push(message.text());
    });
    page.on('pageerror', (error) => complaints.push(error.message));

    await page.goto(`/public/${shareToken}?range=30d`);
    const url = page.url();

    const tab = (name: string) => page.getByRole('tab', { name, exact: true });
    const panel = (card: string, name: string) =>
      page.locator(`[role="tabpanel"][data-card="${card}"][data-tab="${name}"]`);

    // Referrers by name and mark, as on the owner's page.
    const referrers = panel('sources', 'referrer').locator('.rank-row');
    await expect(referrers).toHaveCount(2);
    const reddit = referrers.filter({ hasText: 'reddit.com/r/coffee' });
    await expect(reddit.locator('.rank-icon')).toHaveClass(/fa-reddit-alien/);

    // A row is not a control here: no pointer, and a click loads nothing.
    await expect(reddit).toHaveCSS('cursor', 'auto');
    await reddit.click();
    await panel('pages', 'page').locator('.rank-row').first().click();
    expect(page.url()).toBe(url);

    await expect(panel('devices', 'browser')).toBeHidden();
    await tab('Browser').click();
    await expect(tab('Browser')).toHaveAttribute('aria-selected', 'true');
    await expect(panel('devices', 'browser')).toBeVisible();
    await expect(panel('devices', 'device')).toBeHidden();
    await expect(panel('devices', 'browser').locator('.rank-row')).toContainText('Chrome');

    // The period menu opens, and a period is a link to the same page.
    await page.locator('.tool-range > button').click();
    await page.locator('.tool-pop a', { hasText: 'Last month' }).click();
    await expect(page).toHaveURL(/range=last_month/);
    await expect(page.locator('.tool-range > button')).toContainText('Last month');

    expect(complaints, complaints.join('\n')).toEqual([]);
  });

  test('invalid share token returns 404', async ({ page }) => {
    const response = await page.goto('/public/invalid-token-12345678');
    expect(response?.status()).toBe(404);
  });
});

test.describe('Password Protected Dashboard', () => {
  test('set password on public dashboard', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    // Enable public access first
    await request.put(`/api/v1/websites/${websiteId}/public-access`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { is_public: true },
    });

    // Set password
    const setRes = await request.post('/api/v1/dashboard-password/set', {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { website_id: websiteId, password: 'testpass123' },
    });
    expect(setRes.status()).toBe(200);

    // Check password status
    const statusRes = await request.get(`/api/v1/dashboard-password/status/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    expect(statusRes.status()).toBe(200);
    const status = await statusRes.json();
    expect(status.password_protected).toBe(true);
  });

  test('check if dashboard requires password', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    // Enable public + set password
    await request.put(`/api/v1/websites/${websiteId}/public-access`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { is_public: true },
    });
    await request.post('/api/v1/dashboard-password/set', {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { website_id: websiteId, password: 'testpass123' },
    });

    // Get share token
    const api = new ApiHelper(request);
    const websiteRes = await api.getWebsite(sessionToken, websiteId);
    const shareToken = websiteRes.body.public_share_token;

    // Check password requirement (public endpoint)
    const checkRes = await request.get(`/api/v1/dashboard-password/check/${shareToken}`);
    expect(checkRes.status()).toBe(200);
    const checkBody = await checkRes.json();
    expect(checkBody.password_required).toBe(true);
  });

  test('verify correct password', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    // Enable public + set password
    await request.put(`/api/v1/websites/${websiteId}/public-access`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { is_public: true },
    });
    await request.post('/api/v1/dashboard-password/set', {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { website_id: websiteId, password: 'share-password-9' },
    });

    const api = new ApiHelper(request);
    const websiteRes = await api.getWebsite(sessionToken, websiteId);
    const shareToken = websiteRes.body.public_share_token;

    // Verify with correct password
    const verifyRes = await request.post(`/api/v1/dashboard-password/verify/${shareToken}`, {
      data: { password: 'share-password-9' },
    });
    expect(verifyRes.status()).toBe(200);
    const body = await verifyRes.json();
    expect(body.verified).toBe(true);
  });

  test('verify wrong password fails', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);

    await request.put(`/api/v1/websites/${websiteId}/public-access`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { is_public: true },
    });
    await request.post('/api/v1/dashboard-password/set', {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { website_id: websiteId, password: 'share-password-9' },
    });

    const api = new ApiHelper(request);
    const websiteRes = await api.getWebsite(sessionToken, websiteId);
    const shareToken = websiteRes.body.public_share_token;

    const verifyRes = await request.post(`/api/v1/dashboard-password/verify/${shareToken}`, {
      data: { password: 'wrong-password-9' },
    });
    expect(verifyRes.status()).toBe(200);
    const body = await verifyRes.json();
    expect(body.verified).toBe(false);
  });
});
