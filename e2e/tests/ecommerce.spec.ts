import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createUserWithWebsite } from '../helpers/auth';

test.describe('Ecommerce Tracking - POST /track-ecommerce', () => {
  test('track purchase event with valid tracking code', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'purchase', {
      event_name: 'Product Purchase',
      transaction_id: `txn-${Date.now()}`,
      revenue: 99.99,
      currency: 'USD',
      product_name: 'Pro Plan',
      product_id: 'plan_pro',
    });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.event_id).toBeTruthy();
  });

  test('track purchase with tax and shipping', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'purchase', {
      transaction_id: `txn-full-${Date.now()}`,
      revenue: 149.99,
      currency: 'EUR',
      tax: 12.00,
      shipping: 5.99,
      product_name: 'Enterprise Plan',
      product_id: 'plan_ent',
      product_category: 'Subscription',
      product_brand: 'Argusmetrics',
      product_variant: 'Annual',
      quantity: 1,
      price: 149.99,
    });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('track view_item event', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'view_item', {
      product_name: 'Pro Plan',
      product_id: 'plan_pro',
      price: 99.99,
    });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('track add_to_cart event', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'add_to_cart', {
      product_name: 'Starter Plan',
      product_id: 'plan_starter',
      quantity: 1,
      price: 29.99,
    });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('track begin_checkout event', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'begin_checkout', {
      revenue: 99.99,
      currency: 'USD',
    });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('track refund event', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'refund', {
      transaction_id: `refund-${Date.now()}`,
      revenue: 49.99,
    });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('reject invalid event_type', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'invalid_type', {
      revenue: 10.00,
    });
    expect([422, 500]).toContain(res.status);
  });

  test('reject invalid tracking code', async ({ request }) => {
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce('INVALID1', 'purchase', {
      transaction_id: 'txn-bad',
      revenue: 50.00,
    });
    expect([400, 404, 422]).toContain(res.status);
  });

  test('track purchase with custom properties', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'purchase', {
      transaction_id: `txn-props-${Date.now()}`,
      revenue: 79.99,
      product_name: 'Pro Plan',
      properties: {
        payment_method: 'credit_card',
        coupon: 'SAVE20',
      },
    });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('track purchase with UTM parameters', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackEcommerce(trackingCode, 'purchase', {
      transaction_id: `txn-utm-${Date.now()}`,
      revenue: 59.99,
      product_name: 'Starter Plan',
      utm_source: 'google',
      utm_medium: 'cpc',
      utm_campaign: 'spring_sale',
    });
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  test('bot user agent is filtered', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);

    const res = await request.post('/api/v1/analytics/track-ecommerce', {
      headers: {
        'User-Agent': 'Googlebot/2.1 (+http://www.google.com/bot.html)',
      },
      data: {
        tracking_code: trackingCode,
        event_type: 'purchase',
        event_name: 'Purchase',
        transaction_id: 'txn-bot',
        revenue: 100.00,
        currency: 'USD',
      },
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.success).toBe(true);
    expect(body.message).toContain('Bot');
  });
});

test.describe('Legacy Revenue Tracking - POST /revenue/track', () => {
  test('track revenue via legacy endpoint', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackRevenue(trackingCode, `legacy-${Date.now()}`, 29.99, {
      product_name: 'Starter Plan',
      product_id: 'plan_starter',
    });
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('success');
    expect(res.body.transaction_id).toContain('legacy-');
  });

  test('legacy endpoint with invalid tracking code returns 404', async ({ request }) => {
    const api = new ApiHelper(request);

    const res = await api.trackRevenue('INVALID1', 'txn-bad', 10.00);
    expect([400, 404, 422]).toContain(res.status);
  });

  test('legacy endpoint with different currency', async ({ request }) => {
    const { trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.trackRevenue(trackingCode, `sek-${Date.now()}`, 499.00, {
      currency: 'SEK',
      product_name: 'Premium Plan',
    });
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('success');
  });
});

test.describe('Revenue Dashboard API - GET endpoints', () => {
  test('revenue stats requires authentication', async ({ request }) => {
    const res = await request.get('/api/v1/revenue/999');
    expect([401, 403]).toContain(res.status());
  });

  test('get revenue stats after tracking purchases', async ({ request }) => {
    const { trackingCode, sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Track a purchase via the ecommerce endpoint
    await api.trackEcommerce(trackingCode, 'purchase', {
      transaction_id: `stats-${Date.now()}`,
      revenue: 99.99,
      currency: 'USD',
      product_name: 'Pro Plan',
      product_id: 'plan_pro',
    });

    const stats = await api.getRevenueStats(sessionToken, websiteId);
    expect(stats.status).toBe(200);
    expect(stats.body).toHaveProperty('total_revenue');
    expect(stats.body).toHaveProperty('total_transactions');
    expect(stats.body).toHaveProperty('average_order_value');
    expect(stats.body).toHaveProperty('currency');
    expect(stats.body).toHaveProperty('conversion_rate');
  });

  test('get top products after tracking purchases', async ({ request }) => {
    const { trackingCode, sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    await api.trackEcommerce(trackingCode, 'purchase', {
      transaction_id: `prod1-${Date.now()}`,
      revenue: 99.99,
      product_name: 'Pro Plan',
      product_id: 'plan_pro',
    });

    await api.trackEcommerce(trackingCode, 'purchase', {
      transaction_id: `prod2-${Date.now()}`,
      revenue: 29.99,
      product_name: 'Starter Plan',
      product_id: 'plan_starter',
    });

    const products = await api.getTopProducts(sessionToken, websiteId);
    expect(products.status).toBe(200);
    expect(products.body).toHaveProperty('products');
    expect(products.body).toHaveProperty('total_products');
    expect(Array.isArray(products.body.products)).toBe(true);
  });

  test('get revenue chart data', async ({ request }) => {
    const { trackingCode, sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    await api.trackEcommerce(trackingCode, 'purchase', {
      transaction_id: `chart-${Date.now()}`,
      revenue: 149.99,
      product_name: 'Enterprise Plan',
    });

    const chart = await api.getRevenueChart(sessionToken, websiteId);
    expect(chart.status).toBe(200);
    expect(chart.body).toHaveProperty('data');
    expect(chart.body).toHaveProperty('total_revenue');
    expect(chart.body).toHaveProperty('total_transactions');
    expect(Array.isArray(chart.body.data)).toBe(true);
  });

  test('revenue stats for non-owned website returns 404', async ({ request }) => {
    const { sessionToken } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const stats = await api.getRevenueStats(sessionToken, 999999);
    expect(stats.status).toBe(404);
  });
});

test.describe('Ecommerce Conversion Funnel', () => {
  test('full funnel: view_item → add_to_cart → begin_checkout → purchase', async ({ request }) => {
    const { trackingCode, sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Simulate a full conversion funnel
    await api.trackEcommerce(trackingCode, 'view_item', {
      product_name: 'Pro Plan',
      product_id: 'plan_pro',
      price: 99.99,
    });

    await api.trackEcommerce(trackingCode, 'add_to_cart', {
      product_name: 'Pro Plan',
      product_id: 'plan_pro',
      quantity: 1,
      price: 99.99,
    });

    await api.trackEcommerce(trackingCode, 'begin_checkout', {
      revenue: 99.99,
      currency: 'USD',
    });

    await api.trackEcommerce(trackingCode, 'purchase', {
      transaction_id: `funnel-${Date.now()}`,
      revenue: 99.99,
      currency: 'USD',
      product_name: 'Pro Plan',
      product_id: 'plan_pro',
    });

    // Verify stats reflect the purchase
    const stats = await api.getRevenueStats(sessionToken, websiteId);
    expect(stats.status).toBe(200);
    expect(parseFloat(stats.body.total_revenue)).toBeGreaterThanOrEqual(99.99);
    expect(stats.body.total_transactions).toBeGreaterThanOrEqual(1);
  });
});
