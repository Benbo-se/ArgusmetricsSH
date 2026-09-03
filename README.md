# Argusmetrics (self-host)

Privacy-first, cookieless web analytics — a GDPR-friendly alternative to Google Analytics. Drop in a tiny (<3KB gzipped) script and get real-time dashboards, goals, funnels and e-commerce analytics without cookies, consent banners, or personal-data collection.

> **Status: unmaintained / self-host at your own risk.** This is the open, self-hostable edition of a project that is no longer run as a hosted service. It works and has been security-hardened (see [SECURITY](#security--privacy)), but there is no support, no SLA, and no guarantee of future updates. Audit it yourself before relying on it.

## Quick start (Docker)

```bash
cd docker
cp .env.example .env          # then set SECRET_KEY (and edit POSTGRES_PASSWORD)
docker compose up -d postgres backend
```

The app comes up on **http://localhost:8020** and creates its database schema automatically on first start. Postgres is internal-only (not published to your network); the backend binds to localhost.

- Dashboard / login: `http://localhost:8020/login`
- Health check: `http://localhost:8020/health`

Add the tracking snippet to a site you want to measure (get the code from the dashboard after adding a website):

```html
<script src="http://localhost:8020/static/tracker.min.js"
        data-tracking-code="YOUR_TRACKING_CODE" defer></script>
```

## What works out of the box

Tracking + ingest, dashboards, real-time visitors, goals, funnels, e-commerce/revenue, team members, and the API — all with **no external services required**.

## Optional add-ons (degrade gracefully if unset)

| Feature | Needs | If unset |
|--------|-------|----------|
| Country stats | `GEOIP_DB_PATH` → a MaxMind GeoLite2-Country.mmdb | country = "Unknown"; **no third-party IP lookups ever** |
| Email (magic-link login, reports) | `LETTERMINT_API_KEY` | login links only shown in `DEBUG` mode |

To enable country stats, download `GeoLite2-Country.mmdb` (free MaxMind account) to `backend/app/data/` and set `GEOIP_DB_PATH=/app/data/GeoLite2-Country.mmdb`.

## Configuration

All config is via environment variables (see `docker/.env.example`). Only `SECRET_KEY` is required. Notable hardening flag: `TRUSTED_PROXIES` (only trust `X-Forwarded-For` from listed proxies).

## Tech stack

Python 3.11 · FastAPI · SQLAlchemy 2.0 · Alembic · Jinja2 + HTMX + Alpine.js · PostgreSQL 16 · vanilla-JS tracker.

## Security & privacy

This edition was hardened against a full security review (auth/account-takeover, multi-tenant IDOR, stored XSS, ingest abuse, and GDPR/no-PII leaks). Visitor IPs are never sent to third parties; IP-derived identifiers are truncated/hashed. Still — it is unmaintained, so review the code and keep dependencies patched if you expose it publicly. Run behind HTTPS and set `TRUSTED_PROXIES` if you put it behind a proxy.

## Production deploy (prebuilt images)

Every green commit on `main` publishes ready-to-run images to GHCR, so you don't have to build anything yourself:

- `ghcr.io/benbo-se/argusmetrics-backend` — the FastAPI app
- `ghcr.io/benbo-se/argusmetrics-web` — nginx serving the marketing site + proxying the app

`docker/docker-compose.prod.yml` runs the full stack (TimescaleDB + backend + web) with the web container bound to `127.0.0.1:8021`, meant to sit behind your own TLS-terminating reverse proxy. Full server setup, CI/CD flow (build on green main → gated deploy → health-check → auto-rollback), and rollback instructions: [docker/PRODUCTION.md](docker/PRODUCTION.md). This is also exactly how argusmetrics.io itself is hosted.

## Local development

Same as above; the compose backend mounts the source and you can add `--reload`. Run the test suites with `pytest` (backend) and the Playwright specs under `e2e/`.

## License

[AGPL-3.0](LICENSE). If you run a modified version as a network service, you must offer your source under the same license.
