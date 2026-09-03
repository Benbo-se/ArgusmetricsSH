import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createVerifiedUser, createUserWithWebsite } from '../helpers/auth';

test.describe('Health Check', () => {
  test('GET /health returns healthy', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.health();
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('healthy');
  });
});

test.describe('Websites CRUD', () => {
  test('create website returns tracking code', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    const domain = `https://e2e-create-${Date.now()}.example.com`;
    const res = await api.createWebsite(sessionToken, 'My Site', domain);
    expect(res.status).toBe(201);
    expect(res.body.name).toBe('My Site');
    expect(res.body.domain).toBe(domain);
    expect(res.body.tracking_code).toBeTruthy();
    expect(res.body.tracking_code.length).toBe(8);
  });

  test('list websites returns created site', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    await api.createWebsite(sessionToken, 'Site A', `https://sitea-${Date.now()}.example.com`);
    const res = await api.listWebsites(sessionToken);
    expect(res.status).toBe(200);
    expect(res.body.websites.length).toBeGreaterThanOrEqual(1);
    expect(res.body.websites.some((w: any) => w.name === 'Site A')).toBe(true);
  });

  test('get website by id', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.getWebsite(sessionToken, websiteId);
    expect(res.status).toBe(200);
    expect(res.body.id).toBe(websiteId);
  });

  test('delete website', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const delRes = await api.deleteWebsite(sessionToken, websiteId);
    expect(delRes.status).toBe(200);

    const getRes = await api.getWebsite(sessionToken, websiteId);
    expect(getRes.status).toBe(404);
  });

  test('cannot access another users website', async ({ request }) => {
    const user1 = await createUserWithWebsite(request);
    const user2 = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    const res = await api.getWebsite(user2.sessionToken, user1.websiteId);
    expect([403, 404]).toContain(res.status);
  });
});

test.describe('Goals CRUD', () => {
  test('create and delete a goal', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const createRes = await api.createGoal(sessionToken, websiteId, 'Newsletter Signup', 'newsletter_signup');
    expect(createRes.status).toBe(201);
    expect(createRes.body.name).toBe('Newsletter Signup');
    expect(createRes.body.event_name).toBe('newsletter_signup');

    const delRes = await api.deleteGoal(sessionToken, createRes.body.id, websiteId);
    expect(delRes.status).toBe(200);
  });
});

test.describe('Analytics Stats', () => {
  test('get stats for website with no data', async ({ request }) => {
    const { sessionToken, websiteId } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    const res = await api.getStats(sessionToken, websiteId);
    expect(res.status).toBe(200);
    expect(res.body.total_pageviews).toBe(0);
    expect(res.body.unique_visitors).toBe(0);
  });

  test('stats reflect tracked pageviews', async ({ request }) => {
    const { sessionToken, websiteId, trackingCode } = await createUserWithWebsite(request);
    const api = new ApiHelper(request);

    // Track some pageviews
    await api.track(trackingCode, '/');
    await api.track(trackingCode, '/about');
    await api.track(trackingCode, '/contact');

    const res = await api.getStats(sessionToken, websiteId);
    expect(res.status).toBe(200);
    expect(res.body.total_pageviews).toBeGreaterThanOrEqual(3);
  });
});



test.describe('Unauthenticated access', () => {
  test('websites endpoint requires auth', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.listWebsites('invalid-token');
    expect([401, 403]).toContain(res.status);
  });

  test('stats endpoint requires auth', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.getStats('invalid-token', 1);
    expect([401, 403]).toContain(res.status);
  });
});
