# Runbook

What to do when something is wrong, written so it is useful at three in the
morning by somebody who did not build this.

Every check below assumes you are in `/opt/argusmetrics` and that
`docker compose -f docker/docker-compose.prod.yml` is how you reach the stack.
That is written `$C` here.

## First, three commands

```bash
curl -s -H 'Host: argusmetrics.io' http://127.0.0.1:8021/health | jq
$C ps
$C logs --since 15m backend | tail -50
```

`/health` answers `healthy`, `degraded` or `unhealthy`. Degraded means the
site is serving and tracking is recording, but a scheduled job has not
succeeded when it should have. That is deliberate: an uptime check that only
watches for "down" would never notice a job doing nothing for weeks.

The Host header is not optional. TrustedHost refuses anything else in
production and answers 400 before the health check runs, which looks exactly
like the application being broken.

## Nothing is being recorded

**Check whether it is one site or all of them.**

```sql
SELECT w.domain, count(p.*) AS last_hour
  FROM websites w
  LEFT JOIN pageviews p
    ON p.website_id = w.id AND p."timestamp" > now() - INTERVAL '1 hour'
 WHERE w.is_active
 GROUP BY 1 ORDER BY 2;
```

*One site, zero.* Almost always domain verification. An unverified website
records nothing and the tracking script reports no error: the page loads, the
request goes out, the dashboard stays empty.

```sql
SELECT domain, is_verified, is_active FROM websites WHERE domain = '...';
```

Also worth ruling out: the account is over its monthly limit, if one is set.

```sql
SELECT owner_email, events FROM account_usage
 WHERE period_start = date_trunc('month', now())::date ORDER BY events DESC;
```

*Every site, zero.* Look at the backend log for the tracking endpoint. If
requests are arriving and being refused, the message says why. If nothing is
arriving at all, the problem is in front of the application: host nginx, TLS,
or DNS.

## A scheduled job has stopped

`/health` names it. The history is in the database:

```sql
SELECT job_name, last_run_at, last_success_at, consecutive_failures, last_error
  FROM job_runs ORDER BY job_name;
```

The jobs run in the backend process, so restarting the backend restarts the
scheduler:

```bash
$C restart backend
```

If a job fails repeatedly, `last_error` holds the reason. Retention falling
behind is not urgent; the alert and report jobs not running means customers
are not being told things they expect to be told.

## The disk is filling

The database and the backups share a disk, which is issue #18 and not yet
solved.

```bash
df -h
$C exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT pg_size_pretty(pg_database_size(current_database()))"
du -sh ~/backups/argusmetrics/*
```

Fastest safe relief, in order: delete old backup archives (keeping at least
the two most recent and one verified), then lower `DATA_RETENTION_DAYS` and
let the nightly purge work through it. The purge deletes in batches and drops
whole chunks where it can, so it will not lock the tracking tables, but it
also will not finish in one night on a large backlog. `RETENTION_MAX_ROWS_PER_RUN`
bounds it deliberately.

Do not delete rows by hand from the traffic tables. They are hypertables and
a `DELETE ... WHERE ctid IN (...)` matches the same physical location in every
chunk: that mistake once deleted seven rows when one was due.

## Restoring from a backup

The procedure is not `psql < dump`. A plain restore of a TimescaleDB database
brings back the schema, aborts the data load on a catalog conflict, and leaves
every table empty while looking like it worked.

```bash
scripts/verify-backup.sh ~/backups/argusmetrics/daily/<archive>.sql.gz
```

That restores into a scratch database and compares row counts, chunk count and
policy count against the manifest taken with the dump. Use it to check an
archive before trusting it. To restore for real, read the script: it does the
`timescaledb_pre_restore()` and `timescaledb_post_restore()` bracketing that
makes the difference.

Afterwards, count something. A restore that returns rows without its
row-level security policies is a database every customer can read across.

## Nobody can log in

Sessions live in the database, so a restart does not clear them.

```sql
SELECT count(*) FROM sessions WHERE expires_at > now();
SELECT email, is_verified FROM users WHERE email = '...';
```

An account that is not verified cannot log in, and the error is deliberately
generic so it does not reveal which addresses exist. If email is not being
delivered, verification links appear in the backend log.

To get back into a brand new instance with no accounts at all:

```bash
$C exec backend python -m app.bootstrap
```

It refuses once any account exists.

## Rolling back a deployment

Every deploy tags the commit `PROD-YYYY-MM-DD` and pushes images tagged with
the git SHA. The deploy workflow health-checks and rolls back on its own if
that fails. To roll back by hand: Actions, Deploy, Run workflow, and give the
previous SHA as the tag.

A pre-deploy dump is taken every time and lands in
`~/backups/argusmetrics/pre-deploy/`.

## Metrics

`/metrics` serves Prometheus exposition format and is **off** unless
`METRICS_TOKEN` is set, because what it exposes is business data: pageviews
per hour, how many websites, how many accounts.

```bash
curl -s -H 'Host: argusmetrics.io' -H "Authorization: Bearer $METRICS_TOKEN" \
  http://127.0.0.1:8021/metrics
```

Worth alerting on:

| Metric | Alert when |
|---|---|
| `argus_pageviews_recent{window="hour"}` | far below the same hour a week ago |
| `argus_job_last_success_seconds` | above a day for any job |
| `argus_job_consecutive_failures` | above zero and rising |
| `argus_database_bytes` | growing toward the disk |
| `argus_websites_unverified` | rising, which means people are adding sites and not finishing setup |

The first is the one that matters. Everything else here fails loudly; traffic
quietly stopping is the failure that goes unnoticed for a week.
