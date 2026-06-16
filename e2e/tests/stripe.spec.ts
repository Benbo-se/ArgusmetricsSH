import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createVerifiedUser, createUserWithWebsite } from '../helpers/auth';

test.describe('Stripe Configuration', () => {
  test('GET /stripe/config returns publishable key', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.getStripeConfig();
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('configured');
    expect(res.body).toHaveProperty('publishable_key');
    // Publishable key should start with pk_
    if (res.body.configured) {
      expect(res.body.publishable_key).toMatch(/^pk_/);
    }
  });
});

test.describe('Checkout Session', () => {
  test('create checkout session requires auth', async ({ request }) => {
    const res = await request.get('/api/v1/stripe/create-checkout-session', {
      params: { plan: 'starter' },
    });
    expect(res.status()).toBe(401);
  });

  test('create checkout session with valid plan', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    // Backend returns a 303 redirect to Stripe checkout, or 503 if Stripe not configured
    const res = await request.get('/api/v1/stripe/create-checkout-session', {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { plan: 'starter' },
      maxRedirects: 0,
    });
    // 303 = redirect to Stripe checkout, 400 = Stripe error, 503 = not configured
    expect([303, 400, 503]).toContain(res.status());
  });

  test('create checkout session with invalid plan returns error', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    const res = await request.get('/api/v1/stripe/create-checkout-session', {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { plan: 'nonexistent_plan' },
      maxRedirects: 0,
    });
    // 400 = invalid plan, 503 = Stripe not configured
    expect([400, 503]).toContain(res.status());
  });
});

test.describe('Billing Portal', () => {
  test('billing portal requires auth', async ({ request }) => {
    const res = await request.post('/api/v1/stripe/create-billing-portal-session');
    expect(res.status()).toBe(401);
  });

  test('billing portal for user without subscription', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);
    const res = await api.createBillingPortalSession(sessionToken);
    // User has no Stripe customer ID yet, should get an error
    expect([400, 500]).toContain(res.status);
  });
});

test.describe('Monthly Usage & Quota', () => {
  test('monthly usage returns plan and pageview count', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);
    const res = await api.getMonthlyUsage(sessionToken);
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('monthly_pageviews');
    expect(res.body).toHaveProperty('plan');
    expect(typeof res.body.monthly_pageviews).toBe('number');
  });

  test('new user starts with correct plan via monthly-usage', async ({ request }) => {
    const api = new ApiHelper(request);

    // Free plan user — check plan via monthly-usage endpoint
    const { sessionToken: freeToken } = await createVerifiedUser(request, 'free');
    const freeUsage = await api.getMonthlyUsage(freeToken);
    expect(freeUsage.body.plan).toBe('free');

    // Starter plan user (trial)
    const { sessionToken: starterToken } = await createVerifiedUser(request, 'starter');
    const starterUsage = await api.getMonthlyUsage(starterToken);
    expect(starterUsage.body.plan).toBe('starter');
  });

  test('/me returns user info', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);
    const res = await api.me(sessionToken);
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('email');
    expect(res.body).toHaveProperty('is_verified', true);
  });
});

test.describe('API Token Management', () => {
  test('create, list, and delete API token', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Create token
    const createRes = await api.createApiToken(sessionToken, websiteId, 'Test Token');
    expect(createRes.status).toBe(201);
    expect(createRes.body).toHaveProperty('token');
    expect(createRes.body).toHaveProperty('name', 'Test Token');
    const rawToken = createRes.body.token;
    const tokenId = createRes.body.id;

    // List tokens
    const listRes = await api.listApiTokens(sessionToken, websiteId);
    expect(listRes.status).toBe(200);
    expect(Array.isArray(listRes.body)).toBe(true);
    expect(listRes.body.length).toBeGreaterThanOrEqual(1);

    // Use token to access stats (via X-API-Token header)
    const statsRes = await request.get(`/api/v1/analytics/stats/${websiteId}`, {
      headers: { 'X-API-Token': rawToken },
    });
    expect(statsRes.status()).toBe(200);

    // Delete token
    const deleteRes = await api.deleteApiToken(sessionToken, tokenId, websiteId);
    expect(deleteRes.status).toBe(200);

    // Token should no longer work
    const statsRes2 = await request.get(`/api/v1/analytics/stats/${websiteId}`, {
      headers: { 'X-API-Token': rawToken },
    });
    expect(statsRes2.status()).toBe(401);
  });
});

test.describe('Data Export', () => {
  test('JSON export returns analytics data', async ({ request }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Track a pageview first
    await api.track(trackingCode, '/export-test');

    const res = await api.exportJson(sessionToken, websiteId);
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('website_id', websiteId);
    expect(res.body).toHaveProperty('pageviews');
    expect(Array.isArray(res.body.pageviews)).toBe(true);
  });
});
