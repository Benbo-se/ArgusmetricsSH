import { APIRequestContext } from '@playwright/test';
import { ApiHelper } from './api';

let userCounter = 0;

export function generateTestEmail(): string {
  userCounter++;
  return `test_e2e_${Date.now()}_${userCounter}@test.argusmetrics.io`;
}

export async function createVerifiedUser(
  request: APIRequestContext,
  plan: string = 'starter'
): Promise<{ email: string; sessionToken: string }> {
  const api = new ApiHelper(request);
  const email = generateTestEmail();

  // Signup
  const signupRes = await api.signup(email, plan);
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
  request: APIRequestContext,
  plan: string = 'starter'
): Promise<{
  email: string;
  sessionToken: string;
  websiteId: number;
  trackingCode: string;
  domain: string;
}> {
  const { email, sessionToken } = await createVerifiedUser(request, plan);
  const api = new ApiHelper(request);

  const domain = `https://test-${Date.now()}.example.com`;
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
