# Data map: Argusmetrics

What personal data Argusmetrics holds, where, why, for how long, and what
removes it. One row per place. BenboStandard 06, "Know what personal data you
hold". Written 2026-10-08 from the models, the production schema and row
counts, the server's `docker/.env` (names only, no values), its log and backup
configuration, and the scheduled jobs in `cleanup_service.py`. Update it in
the same PR as any migration that adds a column about a person.

Argusmetrics holds two kinds of personal data. **Its own users**: the people
who log in to the dashboard, for whom it is the controller. **Their visitors**:
the people browsing a customer's website, for whom the customer is the
controller and this instance the processor. Visitor data is pseudonymous by
design: no cookie, no stored address, a visitor hash rebuilt from a salt that
changes daily. Pseudonymous is still personal data under the GDPR, so it is
mapped here like everything else.

Production, 2026-10-08: 1 user, 15 websites, 15 memberships, 30 sessions,
8,702 pageviews, 446 custom events, 1 waitlist entry.

| Data | Where | Why we have it | How long | Removed by |
|---|---|---|---|---|
| Account email, password hash, one-time login code (hashed) | `users` | login | until the account is deleted | `cleanup_service`: unverified after 7 days, verified with no site, no membership and no session after 30 days. On request: `./argus delete-user` |
| Session tokens (hashed), with the account's email | `sessions` | stay logged in | `SESSION_EXPIRY_DAYS` (30) | `cleanup_expired_sessions`, nightly |
| API tokens (hashed) | `api_tokens` | read-only API access to one site | until revoked | revoke in the dashboard; cascades with the website |
| Website owner's email, report and alert recipient addresses | `websites.user_email`, `email_reports_recipient`, `alert_settings.alert_email` | ownership, sending reports and alerts | with the website | deleting the website (`DELETE /websites/{id}`); cascades |
| Team members' emails, who invited them, invitation token | `website_members` | team access | with the website | removing the member or the website; a pending invitation is deleted by the nightly cleanup once its 7 days are up; `./argus delete-user` removes a person's memberships |
| Monthly event count per account email | `account_usage` | the optional monthly limit | with the account | `./argus delete-user` |
| Waitlist email and where it came from | `waitlist` | tell people when signup opens | 30 days after they were told, a year at most | nightly cleanup; `./argus waitlist remove` by hand |
| Visitor hash, path, referrer (sensitive query parameters stripped), country, browser, device, screen size, UTM tags, scroll depth | `pageviews` (TimescaleDB hypertable) | the analytics, for the customer | `DATA_RETENTION_DAYS` (730 in production) | `purge_old_event_data`, nightly: whole chunks dropped, the boundary deleted in batches; or deleting the website |
| As pageviews, plus event name and **free-form properties the customer's site sends** | `custom_events` | custom events, for the customer | 730 days | the same purge. Properties are the customer's choice: if a site sends an email address as a property, it is stored (note 7) |
| Purchases: transaction id, products, revenue, visitor hash, properties | `ecommerce_events`, `ecommerce_transactions` | ecommerce reporting, deduplication | 730 days | the same purge |
| Goal conversions, funnel steps, visitor hash | `goal_conversions`, `funnel_events` | goals and funnels | 730 days | the same purge |
| Recipient address, subject, delivery status of every email sent | `email_logs` | debugging delivery | `EMAIL_LOG_RETENTION_DAYS` (90) | the nightly purge |
| Visitor's IP address | memory, during one tracking request | the visitor hash (truncated to /24 or /48 first) and the country lookup, against a table on this server | the request | never written: not to the database, not to the access logs (#104), not to a third party |
| Path, user agent and site origin of every request; no address, no query string | web container's nginx log (Docker `json-file`) | debugging | 5 × 20 MB per container, and the container is recreated on every deploy | Docker log rotation (`docker-compose.prod.yml`) |
| Application log: request ids, job results, email addresses masked to their domain | backend container log (Docker `json-file`) | debugging | 5 × 20 MB, recreated on deploy | Docker log rotation. `test_no_email_in_logs` fails on an unmasked one |
| Visitor's IP address and request line, **on upstream errors only** | host nginx `error.log` on ghostleads-server | nginx's own error reporting | 14 daily rotations | logrotate. The access log is off for this site's vhost since #104 (gap 6) |
| Everything in the database above | nightly dump at 03:30, `~/backups/argusmetrics/daily/`; a dump before every deploy, `pre-deploy/` | restore | 30 days daily, 7 days pre-deploy, on the host | `backup.sh` and the deploy rotate them. **Not encrypted** (gap 1) |
| The same dumps | off-host, benbo-infra `DBBackups/argusmetrics/`, pulled by `pull-backups.sh` | restore when the host is lost | 14 daily and 30 pre-deploy, as recorded in #70 | benbo-infra rotation. **Not encrypted** (gap 1) |
| Recipient email addresses and message contents | Lettermint, third party, EU (`LETTERMINT_API_KEY` is set) | verification, password reset, invitations, reports, alerts | Lettermint's retention | Lettermint account settings |

Not in this table, because they hold nothing about a person: country ranges
(`ip_country_ranges`, public registry data), `job_runs`, `goals`, `funnels`,
`used_magic_tokens` (a token id and a time). GHCR holds images, not data.
DNS is at Cloudflare in DNS-only mode, so no visitor traffic passes through
it. No Sentry DSN is set, so no error reports leave the server.

## Known gaps

Four more were closed by #144: deletion on request, the waitlist, expired invitations, and addresses in the application log.

1. **Dumps are not encrypted**, on the host or off it, and they hold every row
   above. Tracked in #19, waiting on where the private half of the backup key
   is kept.
2. **The host's nginx `error.log` records the client address** on upstream
   errors, for example during a deploy, and its format cannot be changed. It is
   shared with the other applications on the host. Bounded by 14-day rotation.
   Older host access logs from before #104 (2026-10-05) still hold visitor
   addresses until they rotate out, around 2026-10-19.
3. **Custom event and ecommerce properties are free-form.** The customer's
   site decides what goes in them, and an email address or a name sent there
   is stored for 730 days. The customer is the controller for it; the
   documentation and the DPA (#11) should say plainly that properties must
   not carry personal data.

## Requests

- **Access / export, own users:** what is held about an account is its
  `users` row, its sessions, the websites it owns and its memberships;
  `./argus delete-user --email ADDR` lists it without deleting when the
  confirmation is not given, and `./argus psql` reads the rows themselves. **Customers' visitor data:** the dashboard exports
  CSV and JSON per website (`/api/v1/analytics/export/{id}/csv`, `/json`).
  Individual visitors cannot be looked up: there is nothing to look them up by.
- **Deletion, own users:** `./argus delete-user --email ADDR`. It shows what
  goes (the account, its sessions, the websites it owns with all their
  traffic, its memberships of other websites) and asks for the address again.
  Backups still hold it until they rotate out. Deleting a website on its own
  removes every event recorded for it, through the cascades.
- **Deletion, a visitor of a customer's site:** the hash is rebuilt daily from
  a salt that is never stored, so a visitor cannot be identified to delete
  their rows. The 730-day retention is what removes them. This is stated to
  the customer, who is the controller and receives the request.
