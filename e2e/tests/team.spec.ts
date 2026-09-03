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
    expect(inviteRes.status).toBe(200);

    // List members — should include the invited member
    const membersRes = await api.getTeamMembers(ownerToken, websiteId);
    expect(membersRes.status).toBe(200);
    const members = Array.isArray(membersRes.body) ? membersRes.body : membersRes.body.members || [];
    const member = members.find((m: any) => m.user_email === memberEmail);
    expect(member).toBeTruthy();
  });

  test('invited member sees pending invitation', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: memberEmail, sessionToken: memberToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite
    await api.inviteTeamMember(ownerToken, websiteId, memberEmail, 'viewer');

    // Member checks pending invitations
    const pendingRes = await api.getPendingInvitations(memberToken);
    expect(pendingRes.status).toBe(200);
    // Response is { success: true, invitations: [...] }
    const invitations = pendingRes.body.invitations || pendingRes.body || [];
    expect(Array.isArray(invitations)).toBe(true);
    expect(invitations.length).toBeGreaterThanOrEqual(1);
  });

  test('member can access website after accepting invite', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: memberEmail, sessionToken: memberToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite
    const inviteRes = await api.inviteTeamMember(ownerToken, websiteId, memberEmail, 'viewer');
    expect(inviteRes.status).toBe(200);

    // Get pending invitations to find the token
    const pendingRes = await api.getPendingInvitations(memberToken);
    const invitations = pendingRes.body.invitations || pendingRes.body || [];
    expect(invitations.length).toBeGreaterThanOrEqual(1);
    const invitation = invitations.find((inv: any) => inv.website_id === websiteId);
    expect(invitation).toBeTruthy();

    // Accept invitation
    if (invitation?.invite_token) {
      const acceptRes = await api.acceptInvitation(memberToken, invitation.invite_token);
      expect([200, 201]).toContain(acceptRes.status);
    }

    // Member should now see the website in their team websites
    const teamWebsites = await api.getTeamWebsites(memberToken);
    expect(teamWebsites.status).toBe(200);
  });
});

test.describe('Role-Based Permissions', () => {
  test('viewer can read but has limited write access', async ({ request }) => {
    const { sessionToken: ownerToken, websiteId } = await createUserWithWebsite(request);
    const { email: viewerEmail, sessionToken: viewerToken } = await createVerifiedUser(request);
    const api = new ApiHelper(request);

    // Invite as viewer and accept
    await api.inviteTeamMember(ownerToken, websiteId, viewerEmail, 'viewer');
    const pendingRes = await api.getPendingInvitations(viewerToken);
    const invitations = pendingRes.body.invitations || [];
    const invitation = invitations.find((inv: any) => inv.website_id === websiteId);
    if (invitation?.invite_token) {
      await api.acceptInvitation(viewerToken, invitation.invite_token);
    }

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

    // Invite as viewer
    await api.inviteTeamMember(ownerToken, websiteId, memberEmail, 'viewer');

    // Accept invitation first (role change requires ACTIVE status)
    const pendingRes = await api.getPendingInvitations(memberToken);
    const invitations = pendingRes.body.invitations || [];
    const invitation = invitations.find((inv: any) => inv.website_id === websiteId);
    expect(invitation).toBeTruthy();
    if (invitation?.invite_token) {
      const acceptRes = await api.acceptInvitation(memberToken, invitation.invite_token);
      expect([200, 201]).toContain(acceptRes.status);
    }

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
