# What makes this fast, and what is deliberately not used

Written because two of the obvious answers are unavailable here, and the
reasons are not obvious from the outside. Somebody will reach for both.

## What is in place

**The traffic tables are hypertables**, partitioned by time in seven-day
chunks: `pageviews`, `custom_events`, `goal_conversions`, `funnel_events`,
`ecommerce_events`. A query bounded in time reads only the chunks it needs.
Measured on a development database: a seven-day query touches 2 chunks of 6.

**Retention drops chunks** rather than deleting rows, so removing a year of
data is a file deletion and not a scan. Only the chunk straddling the cutoff
is deleted from, and that in batches.

**Indexes** cover the queries the dashboard actually makes, and duplicates
were removed once already: seventeen indexes covered columns another index
already covered.

**A query budget.** `test_performance_budget` counts the queries each page
issues and fails when one grows. It is not a timing test, which would be
flaky; it counts, which is stable and catches the thing that actually
degrades, a loop that queries per row.

## What cannot be used, and why

Both of these are the standard answers for a TimescaleDB workload, and both
are refused outright on a table with row-level security.

### Compression

```
ERROR: columnstore cannot be used on table with row security
```

Every traffic table carries four policies, and those policies are what stops
one customer reading another's rows. The database enforces the separation
independently of the application, which is what the data processing agreement
describes and what `test_tenant_isolation` proves against an unprivileged
role. Storage is cheaper than that.

### Continuous aggregates

```
ERROR: cannot create continuous aggregate on hypertable with row security
```

And this one has a sharper edge. The refusal guards the **order** and nothing
else. An aggregate created before the policies were enabled keeps working
afterwards, and it is a separate relation carrying policies of its own, which
is to say none. Measured here, as the unprivileged role, against a table whose
policies give it nothing:

```
the source table gives:  0 rows
the aggregate gives:     2 rows
```

So the dangerous path is not adding an aggregate, which fails loudly. It is
disabling row security to add one, or adding one before the policies land.
Then everything works and every customer can read every other customer's
totals, with no error anywhere.

`test_hypertables.py::TestNoContinuousAggregateBypassesThePolicies` fails if
one ever exists.

## If the dashboard does need rollups

It does not yet. The instance in production has enough traffic to be
interesting and nowhere near enough to be slow, and building for a load
nobody has measured is how the wrong thing gets optimised. `#58` is the load
profile that should decide it.

When it does, the shape is an ordinary table that we own:

```
pageview_daily(website_id, day, views, visitors, owner_email)
```

with the same four context policies as every other table, and `owner_email`
filled by a trigger the way the traffic tables already do it, filled nightly
by the scheduler that already records its runs in `job_runs`. Slower to
refresh than a continuous aggregate and entirely under the policies.

The reason to write that down now is that the alternative looks like more
work, and the shortcut is one `ALTER TABLE ... DISABLE ROW LEVEL SECURITY`
away.
