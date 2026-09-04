import { APIRequestContext } from '@playwright/test';
import { ApiHelper, TEST_PASSWORD } from './api';

let userCounter = 0;

export function generateTestEmail(): string {
  userCounter++;
  // The domain matters: the E2E bypass only applies to
  // @test.argusmetrics.io, so a test account cannot be minted for a real one.
  return `test_e2e_${Date.now()}_${userCounter}_${Math.random().toString(36).slice(2, 8)}@test.argusmetrics.io`;
}

export async function createVerifiedUser(
  request: APIRequestContext
): Promise<{ email: string; sessionToken: string }> {
  const api = new ApiHelper(request);
  const email = generateTestEmail();

  const signupRes = await api.signup(email);
  if (signupRes.status !== 201) {
    throw new Error(`Signup failed: ${JSON.stringify(signupRes.body)}`);
  }

  // In dev mode, verify_url is returned in response
  const verifyUrl = signupRes.body.verify_url;
  if (!verifyUrl) {
    throw new Error('No verify_url in response — email backend may be configured');
  }

  // Extract token from verify URL
  const url = new URL(verifyUrl);
  const token = url.searchParams.get('token');
  if (!token) {
    throw new Error('No token in verify URL');
  }

  // Verify
  const verifyRes = await api.verify(token);
  if (verifyRes.status !== 200) {
    throw new Error(`Verify failed: ${JSON.stringify(verifyRes.body)}`);
  }

  return {
    email,
    sessionToken: verifyRes.body.session_token,
  };
}

export async function createUserWithWebsite(
  request: APIRequestContext
): Promise<{
  email: string;
  sessionToken: string;
  websiteId: number;
  trackingCode: string;
  domain: string;
}> {
  const { email, sessionToken } = await createVerifiedUser(request);
  const api = new ApiHelper(request);

  // A timestamp alone collides: parallel workers can share a millisecond, and
  // the domain has a unique constraint that outlives the run, so yesterday's
  // domains are still there today.
  const domain = `https://test-${Date.now()}-${Math.random().toString(36).slice(2, 10)}.example.com`;
  const createRes = await api.createWebsite(sessionToken, 'Test Site', domain);
  if (createRes.status !== 201 && createRes.status !== 200) {
    throw new Error(`Create website failed: ${JSON.stringify(createRes.body)}`);
  }

  return {
    email,
    sessionToken,
    websiteId: createRes.body.id,
    trackingCode: createRes.body.tracking_code,
    domain,
  };
}
