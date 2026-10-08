import { APIRequestContext, expect } from '@playwright/test';

/**
 * Record a pageview, and make sure it was recorded.
 *
 * Every test sends from 127.0.0.1, and /track allows 60 requests a minute per
 * address, so a test that seeds a dozen visits while others are doing the
 * same can be refused with 429 partway through. The refusal used to go
 * unchecked: the test then failed far away, reading 2 pageviews where it had
 * sent 3. This waits out a 429 and fails on anything else, where it happened.
 */
export async function track(
  request: APIRequestContext,
  data: Record<string, unknown>,
  userAgent = 'Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0 Safari/537.36',
) {
  for (let attempt = 0; attempt < 30; attempt++) {
    const r = await request.post('/api/v1/analytics/track', { data, headers: { 'User-Agent': userAgent } });
    if (r.status() === 429) {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      continue;
    }
    expect(r.ok(), `${r.status()} ${await r.text()}`).toBeTruthy();
    const body = await r.json();
    expect(body.success, JSON.stringify(body)).toBe(true);
    return body;
  }
  throw new Error('/track still rate limited after a minute');
}
