import { test, expect } from '@playwright/test';
import { ApiHelper } from '../helpers/api';
import { createVerifiedUser, createUserWithWebsite, generateTestEmail } from '../helpers/auth';

test.describe('Team Invite & Members', () => {
  test('invite team member and list members', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: memberEmail } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite member as viewer
    const inviteRes = await api.inviteTeamMember(ownerToken, websiteId, memberEmail, 'viewer');
    expect([200, 201]).toContain(inviteRes.status);

    // List members — should include the invited member
    const membersRes = await api.getTeamMembers(ownerToken, websiteId);
    expect(membersRes.status).toBe(200);
    const members = Array.isArray(membersRes.body) ? membersRes.body : membersRes.body.members || [];
    const member = members.find((m: any) => m.user_email === memberEmail);
    expect(member).toBeTruthy();
  });

  test('an invitation produces a working link', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: memberEmail } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    const inviteRes = await api.inviteTeamMember(ownerToken, websiteId, memberEmail, 'viewer');
    expect([200, 201]).toContain(inviteRes.status);
    expect(inviteRes.body.invite_url).toBeTruthy();

    // The link has to resolve for someone who is not logged in at all.
    const token = new URL(inviteRes.body.invite_url).searchParams.get('token');
    const detailsRes = await request.get(`/api/v1/websites/invites/${token}`);
    expect(detailsRes.status()).toBe(200);
  });

  test('member can access website after accepting invite', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: memberEmail, sessionToken: memberToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite
    const inviteRes = await api.inviteTeamMember(ownerToken, websiteId, memberEmail, 'viewer');
    expect([200, 201]).toContain(inviteRes.status);

    const inviteToken = new URL(inviteRes.body.invite_url).searchParams.get('token')!;

    const acceptRes = await api.acceptInvitation(memberToken, inviteToken);
    expect([200, 201]).toContain(acceptRes.status);

    // The point of accepting: the shared website is now in their list.
    const teamWebsites = await api.getTeamWebsites(memberToken);
    expect(teamWebsites.status).toBe(200);
    const list = Array.isArray(teamWebsites.body)
      ? teamWebsites.body
      : teamWebsites.body.websites || [];
    expect(list.some((w: any) => w.id === websiteId)).toBe(true);
  });
});

test.describe('Role-Based Permissions', () => {
  test('viewer can read but has limited write access', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: viewerEmail, sessionToken: viewerToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite as viewer and accept, via the link the invite response returns
    const inviteRes0 = await api.inviteTeamMember(ownerToken, websiteId, viewerEmail, 'viewer');
    const viewerInviteToken = new URL(inviteRes0.body.invite_url).searchParams.get('token')!;
    await api.acceptInvitation(viewerToken, viewerInviteToken);

    // Viewer can read stats
    const statsRes = await api.getStats(viewerToken, websiteId);
    expect(statsRes.status).toBe(200);

    // Viewer cannot invite other team members (requires owner/admin)
    const inviteRes = await api.inviteTeamMember(viewerToken, websiteId, 'nobody@example.com', 'viewer');
    expect([403, 404]).toContain(inviteRes.status);
  });

  test('owner can change member role', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: memberEmail, sessionToken: memberToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite as viewer, then accept: a role change needs an ACTIVE membership
    const inviteRes = await api.inviteTeamMember(ownerToken, websiteId, memberEmail, 'viewer');
    const inviteToken = new URL(inviteRes.body.invite_url).searchParams.get('token')!;
    const acceptRes = await api.acceptInvitation(memberToken, inviteToken);
    expect([200, 201]).toContain(acceptRes.status);

    // Change to admin
    const roleRes = await api.changeMemberRole(ownerToken, websiteId, memberEmail, 'admin');
    expect(roleRes.status).toBe(200);

    // Verify role changed
    const membersRes = await api.getTeamMembers(ownerToken, websiteId);
    const members = Array.isArray(membersRes.body) ? membersRes.body : membersRes.body.members || [];
    const member = members.find((m: any) => m.user_email === memberEmail);
    expect(member?.role).toBe('admin');
  });

  test('non-owner cannot invite team members', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: viewerEmail, sessionToken: viewerToken } = await createVerifiedUser(request);
    const { email: thirdEmail } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite viewer
    await api.inviteTeamMember(ownerToken, websiteId, viewerEmail, 'viewer');

    // Viewer tries to invite someone else — should fail
    const inviteRes = await api.inviteTeamMember(viewerToken, websiteId, thirdEmail, 'viewer');
    expect([403, 404]).toContain(inviteRes.status);
  });
});

test.describe('Team Member Removal', () => {
  test('owner can remove team member', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: memberEmail } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite and then remove
    await api.inviteTeamMember(ownerToken, websiteId, memberEmail, 'viewer');

    const removeRes = await api.removeTeamMember(ownerToken, websiteId, memberEmail);
    expect(removeRes.status).toBe(200);

    // Member should no longer appear in list
    const membersRes = await api.getTeamMembers(ownerToken, websiteId);
    const members = Array.isArray(membersRes.body) ? membersRes.body : membersRes.body.members || [];
    const member = members.find((m: any) => m.user_email === memberEmail);
    expect(member).toBeFalsy();
  });
});
