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
