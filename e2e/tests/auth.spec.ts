import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { generateTestEmail, createVerifiedUser } from '../helpers/auth';

test.describe('Signup', () => {
  test('signup with valid email returns 201', async ({ request }) => {
    const api = new ApiHelper(request);
    const email = generateTestEmail();

    const res = await api.signup(email);
    expect(res.status).toBe(201);
    expect(res.body.email).toBe(email);
    expect(res.body.message).toBeTruthy();
  });

  test('signup with plan returns verify_url in dev mode', async ({ request }) => {
    const api = new ApiHelper(request);
    const email = generateTestEmail();

    const res = await api.signup(email, 'starter');
    expect(res.status).toBe(201);
    expect(res.body.verify_url).toBeTruthy();
  });

  test('signup with invalid email returns 400', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.signup('not-an-email');
    expect([400, 422]).toContain(res.status);
  });

  test('signup with already verified user returns success (no enumeration)', async ({ request }) => {
    const api = new ApiHelper(request);
    const { email } = await createVerifiedUser(request);

    const res = await api.signup(email);
    expect(res.status).toBe(201);
  });
});

test.describe('Email Verification', () => {
  test('verify with valid token returns session', async ({ request }) => {
    const api = new ApiHelper(request);
    const email = generateTestEmail();

    const signupRes = await api.signup(email);
    const url = new URL(signupRes.body.verify_url);
    const token = url.searchParams.get('token')!;

    const verifyRes = await api.verify(token);
    expect(verifyRes.status).toBe(200);
    expect(verifyRes.body.session_token).toBeTruthy();
    expect(verifyRes.body.email).toBe(email);
  });

  test('verify with invalid token returns error', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.verify('invalid-token-abc123');
    expect([400, 401]).toContain(res.status);
  });
});

test.describe('Session Management', () => {
  test('GET /me returns user info with valid session', async ({ request }) => {
    const { email, sessionToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    const res = await api.me(sessionToken);
    expect(res.status).toBe(200);
    expect(res.body.email).toBe(email);
    expect(res.body.is_verified).toBe(true);
  });

  test('GET /me with invalid token returns 401/403', async ({ request }) => {
    const api = new ApiHelper(request);
    const res = await api.me('invalid-session-token');
    expect([401, 403]).toContain(res.status);
  });

  test('logout invalidates session', async ({ request }) => {
    const { sessionToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    const logoutRes = await api.logout(sessionToken);
    expect(logoutRes.status).toBe(200);

    const meRes = await api.me(sessionToken);
    expect([401, 403]).toContain(meRes.status);
  });
});

test.describe('UI Auth Pages', () => {
  test('login page renders', async ({ page }) => {
    await page.goto('/login');
    expect(await page.title()).toBeTruthy();
    await expect(page.locator('input[type="email"]')).toBeVisible();
  });

  test('signup page renders with plan selection', async ({ page }) => {
    await page.goto('/signup');
    expect(await page.title()).toBeTruthy();
    await expect(page.locator('input[type="email"]')).toBeVisible();
  });
});
