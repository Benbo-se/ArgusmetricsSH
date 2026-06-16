import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createUserWithWebsite } from '../helpers/auth';

test.describe('Pageview Tracking', () => {
  test('track pageview with valid tracking code', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.track(trackingCode, '/');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('track pageview with invalid tracking code', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.track('INVALID1', '/');
    expect([400, 404]).toContain(res.status);
  });

  test('track multiple pages', async ({ request }) => {
    const { trackingCode, sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    await api.track(trackingCode, '/');
    await api.track(trackingCode, '/about');
    await api.track(trackingCode, '/pricing');
    await api.track(trackingCode, '/contact');

    const stats = await api.getStats(sessionToken, websiteId);
    expect(stats.body.total_pageviews).toBeGreaterThanOrEqual(4);
  });

  test('track pageview with UTM parameters', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.request.post('/api/v1/analytics/track', {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      data: {
        tracking_code: trackingCode,
        path: '/landing',
        referrer: 'https://google.com',
        screen_width: 1920,
        utm_source: 'google',
        utm_medium: 'cpc',
        utm_campaign: 'spring_sale',
      },
    });
    expect(res.status()).toBe(200);
  });

  test('track pageview with custom properties', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.request.post('/api/v1/analytics/track', {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      data: {
        tracking_code: trackingCode,
        path: '/product/123',
        screen_width: 1920,
        properties: {
          category: 'electronics',
          price_range: '100-200',
        },
      },
    });
    expect(res.status()).toBe(200);
  });

  test('duplicate visitor hash counts as one visitor', async ({ request }) => {
    const { trackingCode, sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Same request = same visitor hash
    await api.track(trackingCode, '/page1');
    await api.track(trackingCode, '/page2');
    await api.track(trackingCode, '/page3');

    const stats = await api.getStats(sessionToken, websiteId);
    expect(stats.body.total_pageviews).toBeGreaterThanOrEqual(3);
    // Same IP + UA = 1 unique visitor
    expect(stats.body.unique_visitors).toBe(1);
  });
});

test.describe('Custom Event Tracking', () => {
  test('track custom event', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEvent(trackingCode, 'button_click', { button: 'signup' });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('track event with invalid tracking code', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.trackEvent('INVALID1', 'click');
    expect([400, 404]).toContain(res.status);
  });
});

test.describe('Goal Conversions', () => {
  test('track goal conversion', async ({ request }) => {
    const { trackingCode, sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Create a goal
    await api.createGoal(sessionToken, websiteId, 'Signup', 'signup_complete');

    // Track conversion
    const res = await api.trackEvent(trackingCode, 'signup_complete');
    expect(res.status).toBe(200);
  });
});

test.describe('CSV Export', () => {
  test('export CSV requires auth', async ({ request }) => {
    const res = await request.get('/api/v1/analytics/export/1/csv');
    expect([401, 403]).toContain(res.status());
  });

  test('export CSV with valid auth', async ({ request }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Track some data first
    await api.track(trackingCode, '/');

    const res = await request.get(`/api/v1/analytics/export/${websiteId}/csv`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    expect(res.status()).toBe(200);
    const contentType = res.headers()['content-type'];
    expect(contentType).toContain('text/csv');
  });
});
