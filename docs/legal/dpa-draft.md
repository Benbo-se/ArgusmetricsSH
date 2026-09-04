# Data Processing Agreement — DRAFT, NOT YET REVIEWED

> **This is a draft.** It has not been reviewed by anyone qualified, and it is
> not a legal opinion. It is written to give a lawyer something concrete to
> correct rather than a blank page, and everything in the factual sections is
> checked against what the software actually does rather than what a template
> would assume.
>
> Every place needing a decision or a lawyer is marked **[DECIDE]** or
> **[LAWYER]**. Do not send this to a customer in this state.

---

## Parties

**Processor:** [DECIDE: the legal entity name and organisation number that will
appear on invoices. "Argusmetrics" is the product, not a party.]

**Controller:** the customer named in the order or account, referred to below
as "you".

This agreement applies whenever we process personal data on your behalf
through the Argusmetrics service, and it forms part of our terms of service.

---

## 1. Subject matter, duration, nature and purpose

**Subject matter.** Website analytics: recording that a visit happened to a
page on a website you own, and presenting aggregate statistics about those
visits to you.

**Duration.** For as long as you hold an account with us, plus the retention
period in section 6.

**Nature of the processing.** Collection, storage, organisation, aggregation
and erasure. We do not enrich the data from other sources, we do not combine
it across customers, and we do not use it to build profiles of individuals.

**Purpose.** Producing the statistics you asked for. Nothing else. We do not
use your visitors' data to train models, to sell to advertisers, or for our
own analytics about you.

---

## 2. Categories of data subject

Visitors to the websites you register with the service.

We hold no data about your own customers, employees or contacts, unless you
choose to send it as a custom event property (see section 3).

---

## 3. Categories of personal data

This is the exhaustive list of what is stored per event. It is taken from the
database schema, not from a description.

**Recorded for every pageview:**

| Field | What it is |
|---|---|
| `visitor_hash` | A one-way hash. See "How the visitor hash works" below |
| `path` | The path of the page visited, without the domain |
| `referrer` | Where the visitor came from, if the browser sent it |
| `country` | A two-letter country code |
| `browser` | A browser family, such as "Chrome". Not a full user agent |
| `device_type` | One of desktop, mobile, tablet |
| `screen_width`, `screen_height` | Viewport size |
| `scroll_depth` | How far down the page the visitor reached |
| `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term` | Campaign parameters, if present in the URL |
| `timestamp` | When it happened |
| `properties` | Free-form data you choose to attach. See the warning below |

**Additionally for custom events:** an `event_name` you choose.

**Additionally for ecommerce events:** `transaction_id`, `revenue`,
`currency`, `tax`, `shipping`, `product_id`, `product_name`,
`product_category`, `product_brand`, `product_variant`, `quantity`, `price`.

**What is never stored:** the visitor's IP address, in any form. The full user
agent string. Any cookie or identifier placed on the visitor's device. The
service sets no cookies on your visitors at all.

> **Warning about `properties` and event names.** These fields are free-form
> and are whatever your website sends. If you put a name, an email address or
> an order reference in them, that is personal data you have chosen to send us,
> and it is stored as given. Everything else on this page is designed so that
> it cannot identify a person; these two fields are the exception, and they are
> under your control, not ours.

### How the visitor hash works

This is the part the whole design rests on, so it is described precisely.

Before anything is stored, the visitor's IP address is truncated: IPv4 to the
first three octets (a /24, so 192.168.1.123 becomes 192.168.1.0) and IPv6 to
the first three groups (a /48). The truncated address, the browser's user
agent, your website's domain and a salt that changes every day are hashed
together with a secret key. The result is stored; none of the inputs are.

Three consequences, each of which is enforced in code and covered by tests:

1. **It changes daily.** The same visitor returning tomorrow produces a
   different hash, so a visitor cannot be followed across days.
2. **It cannot single out a person within a network.** Everyone behind the
   same /24 produces the same hash for the same browser.
3. **It is scoped to your site.** The same visitor on another customer's
   website produces a completely different hash, so no two customers can
   correlate a person between them, and neither can we.

[LAWYER: whether this makes the hash non-personal data, or pseudonymised
personal data still within scope, is the question worth an opinion. We have
written this agreement assuming it is in scope, which is the cautious
position.]

---

## 4. Your instructions

We process this data only on your documented instructions, which are: the
configuration you set in the dashboard, and this agreement.

If we believe an instruction breaches data protection law, we will tell you
and may pause that processing until it is resolved.

We will not transfer the data outside the EU or EEA. If that ever changes we
will tell you before it happens, and you may terminate.

---

## 5. Confidentiality

Everyone with access to your data is bound by confidentiality.

[DECIDE: today that is the operator alone. If anyone else gains access,
including a contractor, this section needs to say what binds them.]

---

## 6. Retention and erasure

**Analytics events are kept for 24 months** and then deleted automatically by
a nightly job. Twenty-four months because the dashboard offers a full year with
a comparison against the year before, which requires both years to still exist,
and no longer than that.

**Email delivery logs** (which hold recipient addresses) are kept 90 days.

**On your instruction:** deleting a website deletes its data. Closing your
account deletes everything belonging to you. Both take effect immediately, not
at the next nightly run.

**On termination:** [DECIDE: how many days after termination before everything
is erased, and whether an export is offered first. 30 days is a common answer.
Whatever is chosen must match what the software does.]

Backups are retained separately and are overwritten on their own schedule, so
data deleted on request may persist in a backup for [DECIDE: the backup
retention period, which is currently 30 days in the script and not yet
configured on a server] before it ages out. It is not restored into the live
system except in a disaster recovery.

---

## 7. Security measures

Described concretely, because a list of adjectives is not a measure.

**Isolation between customers is enforced by the database, not only by the
application.** Every table holding customer data has row-level security
policies, and the application connects as a role those policies apply to. A
mistake in application code cannot show one customer another customer's data,
because the database refuses independently. This is verified by automated
tests that connect as an unprivileged role and would fail loudly if that ever
stopped being true.

**Credentials are never stored in a usable form.** Passwords are hashed.
Session tokens are hashed. API tokens are hashed. A copy of the database
grants no access to any account.

**In transit:** all traffic is served over HTTPS. Session cookies are marked
Secure, HttpOnly and SameSite.

**IP addresses never leave the server.** Country lookup uses a local database
on our own machine; no third-party geolocation service is contacted.

**No third-party scripts.** The dashboard loads no external scripts, fonts or
trackers. The tracking script on your site loads nothing beyond itself.

**Least privilege.** The application's database role can read and write rows
but cannot alter the schema.

**Rate limiting** on authentication and on the tracking endpoints.

[LAWYER: Article 32 also expects the measures to be proportionate and
periodically tested. We test the isolation and the escaping automatically on
every change; there has been no external penetration test. Whether that should
be stated here or committed to is a judgement call.]

---

## 8. Sub-processors

You consent to the following, and we will give you notice before adding or
replacing any of them so you can object.

| Sub-processor | Country | What they do | What they can see |
|---|---|---|---|
| Bahnhof | Sweden | Hosts the physical server | The server, as any host can. They do not process the data for their own purposes |
| Lettermint® B.V. | Netherlands | Delivers verification, reset, report and alert emails | Your email address and the contents of those messages. Not your visitors' data |

Lettermint's own infrastructure is in the Netherlands with backups in Germany,
and their published sub-processor list contains no US cloud providers.

[DECIDE: how much notice before a sub-processor changes. 30 days is common.]

---

## 9. Assisting you

**Data subject requests.** If one of your visitors contacts you, there is
usually nothing for us to retrieve or delete: what we hold is a hash that
changes daily and is not linked to a person, so we cannot single out one
visitor's records even if asked. If you send identifying data in event
properties, that is different, and we will help you find and remove it.

**Security incidents.** We will tell you without undue delay after becoming
aware of a breach affecting your data, with what we know at the time.

[DECIDE: a number of hours. GDPR gives the controller 72 hours to notify their
authority, so a processor commitment of 24 or 48 hours is what makes that
possible. Only promise what can be met.]

**Impact assessments and audits.** We will give you the information you
reasonably need for a data protection impact assessment, and allow an audit of
our compliance with this agreement.

[LAWYER: audit rights are the clause most often negotiated. Worth setting the
terms deliberately rather than accepting whatever a customer's template says.]

---

## 10. Liability, term, governing law

[LAWYER: all of it. Liability caps, how this interacts with the main terms,
what survives termination, jurisdiction. Swedish law and Swedish courts is the
obvious starting point given where the company and the server are.]

---

## What to hand a reviewer along with this

- The privacy policy at `/privacy`, which describes the same processing from
  the visitor's side and must not contradict this
- The retention setting: 730 days, in `docker-compose.prod.yml`, with a test
  that fails if it stops matching the policy
- `backend/tests/test_privacy_claims.py`, which tests the three claims in
  section 3 about the hash
- `backend/tests/test_tenant_isolation.py`, which tests the isolation claim in
  section 7 against an unprivileged database role

The point of that list: the factual claims in this agreement are not
aspirations. They are enforced and tested, and the tests can be shown.
