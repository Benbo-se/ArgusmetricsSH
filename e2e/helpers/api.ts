import { APIRequestContext } from '@playwright/test';

export const TEST_PASSWORD = 'e2e-long-enough-password-9';

const API_PREFIX = '/api/v1';

export class ApiHelper {
  constructor(private request: APIRequestContext) {}

  // Signup takes a password now. It used to be a magic link with a plan, from
  // when this was a paid hosted product; both are gone.
  async signup(email: string, password: string = TEST_PASSWORD) {
    const res = await this.request.post(`${API_PREFIX}/auth/signup`, {
      data: { email, password },
    });
    return { status: res.status(), body: await res.json() };
  }

  async login(email: string, password: string = TEST_PASSWORD) {
    const res = await this.request.post(`${API_PREFIX}/auth/login`, {
      data: { email, password },
    });
    return { status: res.status(), body: await res.json() };
  }

  async verify(token: string) {
    const res = await this.request.get(`${API_PREFIX}/auth/verify`, {
      params: { token },
    });
    return { status: res.status(), body: await res.json() };
  }

  async logout(sessionToken: string) {
    const res = await this.request.post(`${API_PREFIX}/auth/logout`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async me(sessionToken: string) {
    const res = await this.request.get(`${API_PREFIX}/auth/me`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async createWebsite(sessionToken: string, name: string, domain: string) {
    const res = await this.request.post(`${API_PREFIX}/websites/`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { name, domain },
    });
    return { status: res.status(), body: await res.json() };
  }

  async listWebsites(sessionToken: string) {
    const res = await this.request.get(`${API_PREFIX}/websites/`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getWebsite(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`${API_PREFIX}/websites/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async deleteWebsite(sessionToken: string, websiteId: number) {
    const res = await this.request.delete(`${API_PREFIX}/websites/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async track(trackingCode: string, path: string, referrer?: string) {
    const res = await this.request.post(`${API_PREFIX}/analytics/track`, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      data: {
        tracking_code: trackingCode,
        path,
        referrer: referrer || '',
        screen_width: 1920,
      },
    });
    return { status: res.status(), body: await res.json() };
  }

  async trackEvent(trackingCode: string, eventName: string, properties?: Record<string, any>) {
    const res = await this.request.post(`${API_PREFIX}/analytics/track-event`, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      data: {
        tracking_code: trackingCode,
        event_name: eventName,
        properties,
      },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getStats(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`${API_PREFIX}/analytics/stats/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async createGoal(sessionToken: string, websiteId: number, name: string, eventName: string) {
    const res = await this.request.post(`${API_PREFIX}/analytics/goals`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { website_id: websiteId.toString() },
      data: { name, event_name: eventName },
    });
    return { status: res.status(), body: await res.json() };
  }

  async deleteGoal(sessionToken: string, goalId: number, websiteId: number) {
    const res = await this.request.delete(`${API_PREFIX}/analytics/goals/${goalId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { website_id: websiteId.toString() },
    });
    return { status: res.status(), body: await res.json() };
  }

  async trackEcommerce(
    trackingCode: string,
    eventType: string,
    data: Record<string, any> = {}
  ) {
    const res = await this.request.post(`${API_PREFIX}/analytics/track-ecommerce`, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      data: {
        tracking_code: trackingCode,
        event_type: eventType,
        event_name: data.event_name || eventType,
        transaction_id: data.transaction_id || null,
        revenue: data.revenue || null,
        currency: data.currency || 'USD',
        tax: data.tax || null,
        shipping: data.shipping || null,
        product_id: data.product_id || null,
        product_name: data.product_name || null,
        product_category: data.product_category || null,
        product_brand: data.product_brand || null,
        product_variant: data.product_variant || null,
        quantity: data.quantity || 1,
        price: data.price || null,
        properties: data.properties || null,
        ...data,
      },
    });
    return { status: res.status(), body: await res.json() };
  }

  async trackRevenue(trackingCode: string, transactionId: string, amount: number, data: Record<string, any> = {}) {
    const res = await this.request.post(`${API_PREFIX}/revenue/track`, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      },
      data: {
        tracking_code: trackingCode,
        transaction_id: transactionId,
        amount,
        currency: data.currency || 'USD',
        product_name: data.product_name || null,
        product_id: data.product_id || null,
      },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getRevenueStats(sessionToken: string, websiteId: number, range: string = '30d') {
    const res = await this.request.get(`${API_PREFIX}/revenue/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { range },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getTopProducts(sessionToken: string, websiteId: number, range: string = '30d') {
    const res = await this.request.get(`${API_PREFIX}/revenue/${websiteId}/products`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { range },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getRevenueChart(sessionToken: string, websiteId: number, range: string = '30d') {
    const res = await this.request.get(`${API_PREFIX}/revenue/${websiteId}/chart`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { range },
    });
    return { status: res.status(), body: await res.json() };
  }

  async health() {
    const res = await this.request.get('/health');
    return { status: res.status(), body: await res.json() };
  }

  async chatbotAsk(message: string, sessionId: string) {
    const res = await this.request.post(`${API_PREFIX}/chatbot/ask`, {
      data: { message, sessionId },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getAiPlans() {
    const res = await this.request.get(`${API_PREFIX}/ai/plans`);
    return { status: res.status(), body: await res.json() };
  }

  // ---- Stripe / Billing ----

  async getStripeConfig() {
    const res = await this.request.get(`${API_PREFIX}/stripe/config`);
    return { status: res.status(), body: await res.json() };
  }

  async createCheckoutSession(sessionToken: string, plan: string) {
    const res = await this.request.get(`${API_PREFIX}/stripe/create-checkout-session`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { plan },
    });
    return { status: res.status(), body: await res.json() };
  }

  async createBillingPortalSession(sessionToken: string) {
    const res = await this.request.post(`${API_PREFIX}/stripe/create-billing-portal-session`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getMonthlyUsage(sessionToken: string) {
    const res = await this.request.get(`${API_PREFIX}/auth/me/monthly-usage`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  // ---- Team ----

  async inviteTeamMember(sessionToken: string, websiteId: number, email: string, role: string) {
    const res = await this.request.post(`${API_PREFIX}/team/invite`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { website_id: websiteId, email, role },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getTeamMembers(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`${API_PREFIX}/team/websites/${websiteId}/members`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async removeTeamMember(sessionToken: string, websiteId: number, email: string) {
    const res = await this.request.delete(`${API_PREFIX}/team/remove`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { website_id: websiteId, email },
    });
    return { status: res.status(), body: await res.json() };
  }

  async changeMemberRole(sessionToken: string, websiteId: number, email: string, role: string) {
    const res = await this.request.put(`${API_PREFIX}/team/role`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { website_id: websiteId, email, new_role: role },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getPendingInvitations(sessionToken: string) {
    const res = await this.request.get(`${API_PREFIX}/team/pending`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async acceptInvitation(sessionToken: string, inviteToken: string) {
    const res = await this.request.post(`${API_PREFIX}/team/accept`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { invite_token: inviteToken },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getTeamWebsites(sessionToken: string) {
    const res = await this.request.get(`${API_PREFIX}/team/websites`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  // ---- Funnels ----

  async createFunnel(sessionToken: string, websiteId: number, name: string, steps: { step: number; name: string; path: string }[]) {
    const res = await this.request.post(`${API_PREFIX}/funnels`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { website_id: websiteId.toString() },
      data: { name, steps },
    });
    return { status: res.status(), body: await res.json() };
  }

  async listFunnels(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`${API_PREFIX}/funnels`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { website_id: websiteId.toString() },
    });
    return { status: res.status(), body: await res.json() };
  }

  async deleteFunnel(sessionToken: string, funnelId: number, websiteId: number) {
    const res = await this.request.delete(`${API_PREFIX}/funnels/${funnelId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { website_id: websiteId.toString() },
    });
    return { status: res.status(), body: await res.json() };
  }

  // ---- Email Reports ----

  async getEmailReportsConfig(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`${API_PREFIX}/email-reports/config/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async configureEmailReports(sessionToken: string, websiteId: number, frequency: string, recipients: string[]) {
    const res = await this.request.post(`${API_PREFIX}/email-reports/configure`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { website_id: websiteId, frequency, recipients },
    });
    return { status: res.status(), body: await res.json() };
  }

  async disableEmailReports(sessionToken: string, websiteId: number) {
    const res = await this.request.post(`${API_PREFIX}/email-reports/disable/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  // ---- AI ----

  async getAiQuota(sessionToken: string) {
    const res = await this.request.get(`${API_PREFIX}/ai/quota`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async getAiInsights(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`/ai-insights/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  // ---- Anomaly Detection ----

  async detectAnomalies(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`${API_PREFIX}/anomalies/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  // ---- API Tokens ----

  async createApiToken(sessionToken: string, websiteId: number, name: string) {
    const res = await this.request.post(`${API_PREFIX}/analytics/tokens`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { website_id: websiteId.toString() },
      data: { name },
    });
    return { status: res.status(), body: await res.json() };
  }

  async listApiTokens(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`${API_PREFIX}/analytics/tokens/${websiteId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  async deleteApiToken(sessionToken: string, tokenId: number, websiteId: number) {
    const res = await this.request.delete(`${API_PREFIX}/analytics/tokens/${tokenId}`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      params: { website_id: websiteId.toString() },
    });
    return { status: res.status(), body: await res.json() };
  }

  // ---- Data Export ----

  async exportJson(sessionToken: string, websiteId: number) {
    const res = await this.request.get(`${API_PREFIX}/analytics/export/${websiteId}/json`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
    });
    return { status: res.status(), body: await res.json() };
  }

  // ---- Public Access ----

  async updatePublicAccess(sessionToken: string, websiteId: number, isPublic: boolean) {
    const res = await this.request.put(`${API_PREFIX}/websites/${websiteId}/public-access`, {
      headers: { Authorization: `Bearer ${sessionToken}` },
      data: { is_public: isPublic },
    });
    return { status: res.status(), body: await res.json() };
  }
}
