# Argusmetrics

Privacy-first, cookieless web analytics you run yourself. A 2.5KB script on your
pages gives you real-time dashboards, goals, funnels and ecommerce reporting
without cookies, without a consent banner, and without sending a visitor's IP
address anywhere.

There is no hosted service. This repository is the whole product, and running
it is the only way to use it.

## Quick start

```bash
cd docker
cp .env.example .env          # set SECRET_KEY, change POSTGRES_PASSWORD
docker compose up -d postgres backend
```

The app comes up on **http://localhost:8020** and migrates its own schema on
first start. Postgres is not published to your network and the backend binds to
localhost.

- Dashboard: `http://localhost:8020/login`
- Health: `http://localhost:8020/health`

Add a website in the dashboard, then put its snippet on your pages:

```html
<script src="http://localhost:8020/static/tracker.min.js"
        data-tracking-code="YOUR_TRACKING_CODE" defer></script>
```

## What you get

Pageviews, unique visitors, real-time, top pages with scroll depth, referrers,
countries, devices and browsers, UTM campaigns, custom events with properties,
goals, funnels, ecommerce and revenue, cross-domain reporting, public share
links (optionally password-protected), team members with roles, scheduled email
reports, traffic-spike alerts, an API with tokens, and a live debug console.

None of it needs an external service.

## Optional extras

| Feature | Needs | Without it |
|---|---|---|
| Country statistics | `GEOIP_DB_PATH` pointing at a MaxMind GeoLite2-Country.mmdb | Country reads "Unknown". No third-party IP lookup happens either way |
| Email (verification, password reset, invitations, reports) | `SMTP_*`, or a Lettermint API key | Verification links are printed to the backend log. Password login works regardless |

For countries, download `GeoLite2-Country.mmdb` (free MaxMind account) into
`backend/app/data/` and set `GEOIP_DB_PATH=/app/data/GeoLite2-Country.mmdb`.

## The first account

Registration is closed on a production instance, so a fresh database has no way
in. Create the first account once, after the first start:

```bash
docker compose -f docker/docker-compose.prod.yml exec backend python -m app.bootstrap
```

It prompts for an address and a password, and refuses as soon as any account
exists. After that, people join by invitation from a website's Team page.

## Configuration

Everything is environment variables, documented in `docker/.env.example`. Only
`SECRET_KEY` has to be set.

The ones worth knowing about before you expose an instance to the internet:

- **`ENABLE_REGISTRATION`** decides whether anyone who finds the URL can create
  an account. The production compose defaults it to `false`.
- **`ENABLE_EMAIL_VERIFICATION`** is on by default. Turning it off makes new
  accounts usable immediately, which is the only way to sign in on an instance
  with no email configured, and is unsafe with registration open. The
  application refuses to start in production with that combination.
- **`TRUSTED_PROXIES`** decides whose `X-Forwarded-For` is believed. Empty means
  none, which is right unless you run behind a proxy. Get it wrong and every
  visitor looks like your proxy.
- **`DATA_RETENTION_DAYS`** defaults to 730 in the production compose, matching
  what the privacy policy says. A test fails if the two stop agreeing.
- **`MONTHLY_EVENT_LIMIT`** and **`MAX_WEBSITES_PER_ACCOUNT`** cap what one
  account may do. The event limit is off by default; a private instance wants
  no limit.

## How the privacy claims are kept

Not marketing copy. Each of these is enforced in code and covered by a test
that fails if it stops being true.

**No cookies and no identifier on the visitor's device.** The script stores
nothing, client side.

**The IP address is never stored, in any form.** Before anything is written it
is truncated (IPv4 to a /24, IPv6 to a /48) and hashed together with the user
agent, your domain and a salt that changes daily. Only the hash is kept. So a
visitor cannot be followed across days, cannot be singled out within a network,
and produces a completely different hash on someone else's site.

**Country lookup is local.** A database file on your own machine. No
third-party geolocation service is contacted.

**Do Not Track is honoured** by the tracking script.

**One customer cannot read another's data, and the database enforces that, not
just the application.** All 11 tables holding customer data carry row-level
security policies (55 of them), and the application connects as a role those
policies apply to. A bug in application code cannot leak across tenants because
Postgres refuses independently. `backend/tests/test_tenant_isolation.py`
connects as an unprivileged role and proves it.

**Credentials are never stored in a usable form.** Passwords, session tokens
and API tokens are all hashed. A copy of the database grants access to nothing.

**No third-party scripts.** The dashboard loads no external script, font or
tracker, and the tracking script loads nothing beyond itself.

**Content-Security-Policy with no unsafe source.** `script-src` is `'self'`
plus a per-request nonce. No `unsafe-inline`, no `unsafe-eval`.

## Tech

Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic, Jinja2 with HTMX and Alpine
(the CSP build), TimescaleDB on PostgreSQL 16, and a vanilla-JS tracker.

The four traffic tables are TimescaleDB hypertables partitioned by time, so a
query over the last week reads a week of chunks rather than the whole table and
retention drops a chunk instead of deleting rows. Compression is deliberately
not enabled: TimescaleDB refuses it on a table with row-level security, and the
isolation guarantee is worth more than the disk.

## Tests

```bash
docker compose -f docker/docker-compose.yml exec backend python -m pytest
cd e2e && npx playwright test
```

270 backend tests and 110 end-to-end tests. They run against a real Postgres
and a real browser; nothing important is mocked.

Some of them are unusual and deliberate:

- `test_tenant_isolation.py` connects as an unprivileged role, because the
  development database connects as the table owner, and policies never apply to
  the owner. Without a second role these assertions would pass while proving
  nothing.
- `test_csp.py` and `e2e/tests/csp.spec.ts` exist because Alpine's CSP build
  does not throw on an expression it cannot evaluate. It warns to the console
  and renders nothing, so a page loads, looks right, and a control silently
  does not work. The e2e test reads the browser console.
- `test_promises_match_config.py` compares the retention period in the privacy
  policy against the one in the compose file.
- `test_performance_budget.py` counts the queries each page issues and fails if
  one grows.

## Production

Every green commit on `main` publishes images to GHCR:

- `ghcr.io/benbo-se/argusmetrics-backend`
- `ghcr.io/benbo-se/argusmetrics-web` (nginx serving the marketing site and
  proxying the app)

`docker/docker-compose.prod.yml` runs the stack with the web container on
`127.0.0.1:8021`, meant to sit behind your own TLS-terminating reverse proxy.
Server setup, the CI/CD flow and rollback are in
[docker/PRODUCTION.md](docker/PRODUCTION.md).

**Back up before you rely on this.** A plain `pg_dump` of a TimescaleDB
database restores the schema and then aborts the data load on a catalog
conflict, leaving every table empty while looking like it worked. The restore
has to be bracketed with `timescaledb_pre_restore()` and
`timescaledb_post_restore()`. `scripts/verify-backup.sh` does it correctly, and
CI performs a real dump-and-restore on every run and counts the rows that come
back.

## Development

The compose file mounts the source and runs uvicorn with `--reload`. Templates
are read from disk on every render, so without reload the two disagree and
tracebacks point at the wrong line.

## Contributing

Issues and pull requests are welcome. If you change behaviour, the test that
would have caught the old behaviour is the part worth writing first.

## License

Copyright (c) 2026 Reda Ekengren.

Licensed under the GNU Affero General Public License v3.0. The complete
license text is in [LICENSE](LICENSE).

The clause that matters most for a product like this one: if you run a
modified version as a network service, you must offer its complete
corresponding source to the users of that service.
