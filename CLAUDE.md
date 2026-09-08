# CLAUDE.md

For the next session, mine or yours. Not a second README: the README says what
Argusmetrics is and how to start it, this says what will bite you.

Project standard: [BenboStandard](https://github.com/Benbo-se/BenboStandard).
Estate context: [benbo-infra](https://github.com/Benbo-se/benbo-infra).

## First, the one that has cost the most time

**There are two repositories with almost the same name.**

| | |
|---|---|
| `Benbo-se/ArgusmetricsSH` | public, three workflows, deploy secrets. **This one is live.** |
| `RedaEkengren/argusmetrics.io` | private, personal, a GitHub Pages site, last deployed 2026-02-22, Pages now off. Dead. |

A local clone called `argusmetrics/` may well point at the dead one. Check
`git remote -v` before believing anything you read. Confirmed live 2026-09-08:
`argusmetrics.io` answers `Server: nginx/1.24.0 (Ubuntu)` rather than GitHub
Pages, and `/health` matches what this repo's deploy workflow greps for.

## What is load-bearing

- **The server's checkout at `/opt/argusmetrics`.** The application comes from
  GHCR, but compose reads `docker/docker-compose.prod.yml` and `docker/.env`
  from the checkout, and the deploy does `git reset --hard origin/main` on it.
  Compose and nginx config changes therefore ship with the release; `.env` is
  gitignored and survives the reset.
- **`docker/.env` on the server.** Six required variables. `docker/.env.example`
  is the list. Nothing else holds them.
- **`site/` is generated and committed.** `scripts/build_site.py` renders it
  from `site-src/`. nginx serves plain files, so the marketing site stays up
  when the backend does not. CI runs `--check` and fails if the two have
  drifted, which is the whole point of generating them.

## Traps, with the reason attached

- **`BASE_URL` must not carry a port.** `allowed_hosts` is derived from it, and
  nginx forwards `Host` without a port, so a `BASE_URL` with one makes the app
  answer 400 to everything.
- **A restore needs two roles created first**, `argusmetrics` and `argus_app`.
  Without them a dump produces 48 `role "argus_app" does not exist` errors. No
  data is lost, but the grants are wrong. Proven 2026-09-08: restoring the
  off-host copy took 3 seconds, 21 of 21 tables, all row counts identical.
- **A dump also emits 11 `ONLY option not supported on hypertable operations`
  and one duplicate key in `_timescaledb_catalog.metadata`.** Both are
  TimescaleDB's normal pg_dump behaviour. Do not chase them.
- **`grep -q` under `set -o pipefail` fails the pipeline it succeeds in.** It
  exits at the first match, closing the pipe, and whatever writes to it dies of
  broken pipe. This cost four CI runs on 2026-09-08 before the error message
  was improved enough to see it. Use bash pattern matching instead.
- **`pg_isready` without `-h` asks the unix socket.** The postgres image runs a
  temporary server during initialisation that listens on the socket only, so
  the guard says ready while port 5432 is still closed.
- **A wait loop must fail when it runs out.** One in CI only `break`ed, so a
  database that never came up was reported as a broken application image.

## Decisions already made

- **Deploy over SSH, not a self-hosted runner.** The repo is public and a fork's
  pull request could run code on the server. This is the estate's only
  long-lived credential, and BenboStandard 02 documents it as correct *for this
  constraint*: dedicated key, non-root account, gated deploy, dump and
  auto-rollback. All four are implemented; do not "simplify" any of them away.
- **The deploy is gated twice**, by `environment: production` and by the repo
  variable `DEPLOY_ENABLED`. `workflow_run` after green CI does the rest.
- **CI triggers on `pull_request`, never `pull_request_target`.** On a public
  repo that is the line that keeps secrets away from forks.
- **Actions are pinned to commit SHAs** with the version as a trailing comment,
  so Dependabot still reads them. `appleboy/ssh-action` holds the server key; a
  moving tag there is not a style question.
- **`timescale/timescaledb` is pinned by digest** in the prod compose file.

## Deliberately not done

- **`backend` and `web` have no compose healthcheck.** The deploy checks the
  whole chain from outside, which is what matters. The cost is that
  `docker compose ps` cannot tell you much between deploys.
- **Backups are not encrypted.** `scripts/backup.sh` supports
  `BACKUP_GPG_RECIPIENT` and warns when it is unset, on the grounds that an
  unencrypted backup beats no backup. It is unset. The dumps hold every
  customer's email address and every visitor hash. See issue #70.
- **The schedule is not in the repository.** `scripts/backup.sh` is committed;
  whatever runs it nightly at 03:30 is not. A rebuilt server would come up with
  everything restored and nothing taking backups, silently. Same shape as the
  bug BenboStandard 01 describes under "The schedule counts as infrastructure".
  See issue #70.

## Where things are

| | |
|---|---|
| `backend/app/` | FastAPI: routers, services, models, `scheduled_tasks.py` |
| `backend/alembic/` | migrations, run by the entrypoint on start |
| `docker/` | both compose files, both Dockerfiles, both nginx configs, `PRODUCTION.md` |
| `site-src/` → `site/` | marketing site source and generated output |
| `scripts/` | `backup.sh`, `verify-backup.sh`, `build_site.py` |
| `argus` | the server-side CLI: `ps`, `logs`, `health`, `admin`, `backup`, `psql` |
| `e2e/` | Playwright |
| `wordpress-plugin/`, `integrations/` | published integrations |

## `/health` is the good part

It reports per scheduled job: `seconds_since_success`, `max_age_seconds`,
`overdue`, `consecutive_failures`, `last_error`, plus `stalled_jobs`. That is
the estate's reference implementation, now written into BenboStandard 03, and
`benbo-infra`'s estate check reads it. Do not reduce it to `{"ok": true}`.
