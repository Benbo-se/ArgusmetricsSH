# Reporting a security problem

Report it privately first. Use GitHub's **Report a vulnerability** button under
Security on this repository, which opens a private advisory. If that is not
available to you, open a normal issue saying only that you have found something
and asking for a private channel, with no details in it.

Please do not open a public issue describing the problem, and do not post it
anywhere public, until there is a fix people can install.

## What to expect

This is a small project maintained by one person, so be realistic about the
timeline: an acknowledgement within a few days, and a fix as fast as the
severity warrants. You will be told when it ships and credited unless you would
rather not be.

## What is in scope

Anything in this repository, and anything about how a default deployment
behaves. The things worth looking hardest at, because they are what the product
promises:

- **Isolation between tenants.** Every table holding customer data has
  row-level security policies and the application connects as a role those
  policies apply to. A way to read another account's data is the most serious
  bug this project can have.
- **The visitor hash.** The IP is truncated and hashed with a daily salt, and
  the raw address is never stored. Anything that reverses that, or that lets
  one site's hashes be correlated with another's, breaks the central privacy
  claim.
- **Authentication and sessions**, including invitations and share links.
- **The tracking endpoints**, which are unauthenticated by design and take
  input straight from visitors' browsers.
- **Injection of any kind**, including into the dashboard through data a
  visitor controls.

## What is out of scope

- Findings that require an attacker to already have database or shell access on
  the server.
- Missing hardening headers with no demonstrated impact.
- Reports from automated scanners with no working example.
- Denial of service by sending very large volumes of traffic. Rate limits exist
  and are configurable; exhausting a server you are allowed to send traffic to
  is not a vulnerability.
- Anything about an instance somebody else runs. This software is self-hosted,
  so a deployment's configuration is that operator's responsibility, not this
  project's. Report it to them.

## Supported versions

The `main` branch. There are no long-term support branches, and a fix will not
be backported to an older tag. Self-hosted instances should track `main` or
the tagged releases built from it.
