# BUSS Startup Support

The registration and coaching app for BUas Business Startup Support (BUSS). It replaces the
Microsoft Form: students register directly in the app, and coaches use the same app to manage
intakes, follow progress and keep notes.

See [docs/PLAN.md](docs/PLAN.md) for the data model, pages and build order.

**Status:** steps 1–11 of 12 are done (data model, seed data, admin, public registration form, emails, intake queue, student and startup records, pipeline board, activity log and follow-ups, dashboard, export, spreadsheet import, staff sign-in and roles, GDPR tools). All 12 steps are done; see *Go-live* for what is left.

## Stack

Django 5.2 LTS · PostgreSQL (production) / SQLite (local) · server-rendered templates · Docker Compose.

## Local development (no Docker)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # optional; defaults work locally
export DJANGO_DEBUG=1
python manage.py migrate
python manage.py createcachetable   # used by the form's rate limit
python manage.py seed_demo      # reference data + fake students + dev logins
python manage.py runserver
```

The registration form is at http://localhost:8000/register/ and the staff app at
http://localhost:8000/staff/ (the configuration admin is at http://localhost:8000/admin/). Log in as `admin` or as a coach's first name in lower case
(e.g. `shival`), using the password `buss-dev-2026`. These logins are for development only.

Run the tests with `pytest`.

### Coach photos and bios

`seed_reference` reads the coach photos and bios from `seed_data/private/` if that folder exists
(`coaches.json` plus `coaches/<first-last>.jpg`). The folder is **git-ignored** because the
repository is public and the material comes from the internal SharePoint page. Without it, coaches
are created with their names and academies only, and admins can add photos and bios in
*Admin → Coaches*.

## Test server for colleagues (Render)

[`render.yaml`](render.yaml) sets up a test environment with fake data on Render (Frankfurt).
Step-by-step instructions: [docs/DEPLOY-RENDER.md](docs/DEPLOY-RENDER.md); a guide for testers:
[docs/TESTING-GUIDE.md](docs/TESTING-GUIDE.md). Reset the demo data with
`python manage.py seed_demo --reset`.

## Running with Docker

```bash
cp .env.example .env
docker compose up --build
docker compose exec web python manage.py seed_demo --force   # optional demo data
docker compose exec web python manage.py createsuperuser      # real admin account
```

On every start, the container applies migrations and runs `seed_reference` (which is idempotent
and never overwrites admin edits).

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DJANGO_DEBUG` | `1` locally, `0` in production | `0` |
| `DJANGO_SECRET_KEY` | Required when debug is off | — |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host names | `localhost,127.0.0.1` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | e.g. `https://buss.buas.nl` | — |
| `DATABASE_URL` | `postgres://user:pass@host:5432/db`; empty = SQLite | SQLite |
| `POSTGRES_PASSWORD` | Used by docker-compose | `buss-dev-password` |
| `DJANGO_TRUST_X_FORWARDED_FOR` | `1` behind a reverse proxy, so rate limiting sees the real client IP | `0` |
| `DJANGO_MEDIA_ROOT` | Where uploaded photos are stored | `./media` |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` | Staff sign-in with BUas accounts (see *Staff sign-in and roles*) | — (disabled) |
| `ENTRA_ALLOWED_DOMAINS` | Email domains that may sign in | `buas.nl` |
| `ENTRA_ROLE_MAP` | Entra app roles → BUSS roles; empty = roles only via the Team page | `BUSS.Admin=Admin,BUSS.Coach=Coach` |
| `LOCAL_LOGIN_ENABLED` | Username/password sign-in (development) | on with `DJANGO_DEBUG=1`, else off |
| `SITE_URL` | Public address, used for links and the logo in emails | `http://localhost:8000` (on Render: its address) |
| `DEMO_MODE` | `1` on a test environment: banner on every page, hidden from search engines, fake data on first start | `0` |
| `DEMO_PASSWORD` | Password of the demo logins created by `seed_demo`; required on a server | `buss-dev-2026` locally |
| `EMAIL_PROVIDER` | `console`, `smtp` or `graph` | `console` |
| `DEFAULT_FROM_EMAIL`, `EMAIL_REPLY_TO` | Sender and reply-to address | `startupsupport@buas.nl` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL` | SMTP settings | port 587, TLS on |
| `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `GRAPH_SENDER` | Microsoft Graph sender | sender `startupsupport@buas.nl` |

In production, run the app behind a reverse proxy that terminates HTTPS and redirects HTTP to HTTPS.

## Staff sign-in and roles

Staff sign in with their **BUas account** (Microsoft Entra ID, OpenID Connect with PKCE). The public
registration form needs no sign-in. There are two roles:

| | Coach | Admin |
|---|---|---|
| Dashboard, intake queue, students, startups, pipeline, activity log, follow-ups, export, walk-ins | ✓ | ✓ |
| Edit form content (page texts, option lists, coach profiles, email templates, partners) | ✓ | ✓ |
| Read "admin only" notes, merge students, import data, see unassigned follow-ups | | ✓ |
| Team & roles, app settings, pipeline stages, privacy statement, user accounts | | ✓ |

Coaches see all records, with their own caseload shown by default.

**Who may sign in:** BUas accounts (tenant `ENTRA_TENANT_ID`, email domain in `ENTRA_ALLOWED_DOMAINS`)
that either have a BUSS **app role** in Entra ID, or were added by an admin on *Admin → Team & roles*
(matched on email the first time, then on the permanent Entra object ID). Anyone else is refused
with an explanation. Deactivating someone on the Team page ends their access immediately. App roles,
when used, are applied at every sign-in, so removing someone's role in Entra ID removes their access.
Signing out also signs out of the Microsoft session. Password sign-in exists for local development
only and is off in production unless `LOCAL_LOGIN_ENABLED=1`. The configuration admin (`/admin/`)
uses the same sign-in.

**What BUas IT needs to set up** (Entra admin centre → App registrations → New registration):

1. Name e.g. *BUSS Startup Support*, single tenant (BUas only).
2. Redirect URI (Web): `https://<your-host>/oidc/callback/`; front-channel logout URL:
   `https://<your-host>/staff/login/`.
3. *Certificates & secrets*: create a client secret → `ENTRA_CLIENT_SECRET`. Note the *Application
   (client) ID* → `ENTRA_CLIENT_ID` and *Directory (tenant) ID* → `ENTRA_TENANT_ID`.
4. *Token configuration*: add the optional ID-token claims `email`, `given_name` and `family_name`.
5. Optional, recommended: *App roles* `BUSS.Admin` and `BUSS.Coach` (allowed member types: users/groups);
   then in *Enterprise applications → BUSS Startup Support → Users and groups* assign coaches and admins,
   and set *Assignment required* to *Yes* so only assigned people can sign in.
   Without app roles, add people on the Team page instead (and set `ENTRA_ROLE_MAP=` empty).

No Microsoft Graph API permissions are needed for sign-in (only `openid`, `email`, `profile`). The same
app registration can also hold the *Mail.Send* permission for sending email (see *Email*), or you
can use a separate one.

For local development keep `DJANGO_DEBUG=1` and use the demo logins; the sign-in page then shows
the password form (and the BUas button too, if the `ENTRA_*` variables are set).

## Intake queue

*Staff → Intake queue* lists registrations by working days left until the intake deadline:
overdue rows are red, rows due within the configured number of days (default 2) are amber. The
clock stops when a coach records that the intake has been **arranged**; the day it was **held**, who
held it and the coach for the coaching track are recorded separately and also appear in the
startup's activity log. Assigning a coach shows each coach's current caseload; for graduation-track
students a coach from the student's own domain needs an explicit confirmation.

Deadlines skip weekends, Dutch public holidays and the closure days in *Admin → Closure days*.
Adding or removing a closure day recalculates the deadlines of registrations still waiting.

## Students and startups

*Staff → Students* and *Staff → Startups* list all records with search and filters (stage, coach,
domain, study year, graduation track, paying customers, validated idea, tags, archived). Coaches see
their own caseload by default and can switch to *Everyone*. Records can be edited and archived; every
change is in the audit log and shown under *Change history*. *Add walk-in* registers a student in
person with the same questions as the public form (optionally emailing a confirmation).

Admins can merge duplicate students from the student page: registrations, ideas and follow-ups move
to the record you keep, nothing on that record is overwritten, and the duplicate is archived with a
pointer to the kept record.

## Pipeline

*Staff → Pipeline* shows startups per stage as a **board** (drag a card to another column, or use
*Move to…* on the card, which also works with the keyboard) or as a **list** with a stage menu per row.
It uses the same filters as the startups list. Closed stages (Alumni, Stopped) are collapsed until you
choose to show them. Every move is written to the startup's activity log as a stage change (which
does not count as "activity" for the inactivity warning) and to the audit log. Stages are configured
in *Admin → Pipeline stages*: name, order, colour, and whether a stage is closed or marks the intake
as scheduled/done.

## Activity log and follow-ups

Each startup page has an **activity log**: notes, meetings, emails, event attendance and referrals,
each with a date and author. Intakes and stage changes are added automatically (read-only). The
author or an admin can edit or delete an entry; admins can mark an entry *admin only* for sensitive
information. Adding an entry can create a follow-up in the same step.

**Follow-ups** are reminders with a due date and an assignee, on a startup or a student. *Staff →
Follow-ups* shows *This week* (overdue plus due until Sunday), *Later* and *Done*, for yourself or
everyone (admins also see *Unassigned*). Automatic reminders (e.g. missing programme approval) have
no assignee and count as yours when you coach the startup. The menu shows how many of yours are
overdue or due this week.

## Dashboard

*Staff → Dashboard* (the start page after logging in) shows, for a chosen period (last 3/6/12
months, this academic year from 1 September, or all time):

- registrations in the period, the share of intakes arranged within the promised working days, the
  number waiting for an intake (and overdue) and the number of active startups;
- registrations per month and per domain, with a table view and the monthly intake turnaround.

And the current situation ("now"): startups per stage, caseload per coach, graduation-track students
with missing approval or a hand-in date within 8 weeks (or already passed), and active startups with
no activity for the number of weeks in *App settings* (stage changes don't count as activity).

**Intake turnaround** counts registrations whose intake was arranged, plus those still waiting past
their deadline (late); registrations still within their deadline are not counted yet.

## Export

The *Students*, *Startups* and *Pipeline* pages have **Excel** and **CSV** buttons that export exactly
the list you are looking at (same search and filters, including "my caseload" for coaches).

- **Excel** has real dates, a frozen header row with filters, and an *About this export* sheet with
  who exported it, when, the filters used and a privacy reminder.
- **CSV** is comma-separated UTF-8 (with BOM, so Excel shows accented names correctly).
- Text that a spreadsheet would run as a formula is neutralised (CSV injection). In CSV this
  means values starting with `=`, `+`, `-` or `@` get a leading apostrophe (e.g. phone numbers like
  `'+31 6…`); in Excel files only values starting with `=` need it.
- Every export is logged under *Admin → Students & startups → Exports* (who, which list, filters, rows).

## Importing historical data

*Staff → Import* (admins only) imports the BUSS coach overview or a Microsoft Forms export (.xlsx):

1. **Upload and choose a sheet** (e.g. `2026-2027`). The file is kept only until a sheet is chosen.
2. **Map columns and values.** Suggestions are pre-filled: columns by their headers; study programmes
   to a domain and study year (misspellings such as "Buas Emplyee" or "Data Science &AI" are
   recognised); coach first names to coaches; yes/no answers; and the colour of the name cell
   (green = active, orange = inactive, red = finished, blue = employee) to a pipeline stage and tag.
3. **Preview** every row: new or linked to a known student (same student number or email), skipped
   (imported before) or an error, with warnings such as an unknown coach, a missing student number,
   a team of founders in one cell ("Anna Smit & Bram de Vries") or a missing hand-in date.
4. **Import.** Nothing is saved before this step, no emails are sent and the uploaded rows are deleted
   afterwards.

Imported registrations get the default date (1 September of the sheet's academic year) unless the
file has one; such dates are marked as estimated and left out of the monthly dashboard figures.
They have no intake deadline, so they never appear in the intake queue, but they do count in the
pipeline and the coach caseload. The original row is kept with the registration for reference.
Students without a known study programme get the hidden domain "Unknown (imported)". Each row has a
stable import key, so importing the same sheet again skips rows that are already in.

## Privacy (GDPR)

*Staff → Admin → Privacy (GDPR)* (admins only) and the *Privacy (GDPR)* box on a student's page:

- **Download data** (right of access / portability): a JSON file with everything held about the
  student: their details, merged duplicate records, registrations with the answers as submitted,
  consent time and privacy-statement version, startups with the activity log, graduation track,
  follow-ups, the email log and the change history (which fields changed, by whom, not the values).
  Co-founders appear only as a count.
- **Anonymise** (the default): names become "Anonymised / student #id"; student number, email, phone,
  form answers, comments, graduation topic and supervisor are removed; follow-ups are deleted; a
  startup only they founded is blanked and archived (its activity notes become "[removed]"); from a
  startup shared with others they are only removed as founder. Domain, study year, stage, coach and
  dates stay, so the dashboard figures remain correct.
- **Delete**: removes the student and everything only they are part of. Use when anonymising is not
  enough.
- Both need a reason (without personal data) and a confirmation tick. They also remove the audit-log
  history of those records (it contains old values) and the "new registration" notifications.
- Every export, anonymisation and deletion is recorded in the *privacy action log* on that page, by
  record number only.

**Retention.** *Admin → App settings → retention period* (default 2 years). The Privacy page lists
students with no registration, activity or change within that period (this covers alumni too: once
a startup is closed nothing happens any more) and lets you anonymise them in one go. Run the
housekeeping command daily, e.g. from cron:

```bash
docker compose exec -T web python manage.py retention_check
```

It reminds admins in-app when records are due (it never anonymises by itself), and deletes in-app
notifications older than a year, email-log entries older than the retention period, and uploaded
import files that were never imported.

**Other safeguards:** consent is stored with a timestamp and the privacy-statement version; changes to
students, registrations and startups are in the audit log (*Admin → Audit log*; student number and
phone are masked); every export is logged; no data is sent to third-party services (no CDN, analytics
or external CAPTCHA). Email goes only through the sender you configure (SMTP or BUas's own Microsoft
365 tenant).

## Email

After each registration the app sends:

1. a **confirmation** to the student, with a summary of their answers;
2. a **notification** to BUSS staff (*Admin → App settings*: by email to the staff address, in-app for
   admins, or both).
   Returning students and graduation-track students without approval are flagged.

The texts are editable under *Admin → Form content & settings → Email templates*. Placeholders such
as `{{ first_name }}` are listed on each template; use the action **Send a test to my own email
address** to check changes. Every email is logged under *Admin → Students & startups → Sent emails*
(recipient, subject and status only, never the content). A failed email never blocks the
registration, and admins can resend it from that list with the **Send again** action.

**Choosing a sender** (`EMAIL_PROVIDER`):

- `console` (default) prints emails to the log, which is handy locally. To see them as real emails, run
  `docker compose --profile dev up` and open the Mailpit inbox at http://localhost:8025 (see `.env.example`).
- `smtp`: any SMTP server, e.g. BUas's relay.
- `graph`: Microsoft Graph, sending as the `startupsupport@buas.nl` mailbox. BUas IT needs to:
  1. create an Entra ID app registration with the **Mail.Send** *application* permission (admin consent);
  2. restrict it to the BUSS mailbox with an Exchange
     [application access policy](https://learn.microsoft.com/graph/auth-limit-mailbox-access), so the
     app cannot send as anyone else;
  3. give you the tenant ID, client ID and a client secret for `GRAPH_*`.

  The same app registration can later be reused for staff sign-in (step 11).

## Backups

Back up two things: the PostgreSQL database and the `media` volume (coach photos).

```bash
# Database
docker compose exec -T db pg_dump -U buss -Fc buss > buss-$(date +%F).dump
# Restore
docker compose exec -T db pg_restore -U buss -d buss --clean < buss-YYYY-MM-DD.dump
# Media
docker run --rm -v startupsupport_media:/m -v "$PWD":/b alpine tar czf /b/media-$(date +%F).tgz -C /m .
```

Backups contain personal data: store them encrypted, at a BUas-approved location, and keep them
no longer than the retention period.

## Go-live

What is left before real students use it (needs BUas IT or a decision by BUSS):

1. **Hosting**: a BUas-approved server or cloud subscription running `docker compose` with PostgreSQL,
   HTTPS in front, and `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `SITE_URL` set.
2. **Entra ID app registration** for staff sign-in (see *Staff sign-in and roles*), then turn
   `LOCAL_LOGIN_ENABLED` off.
3. **Email sender**: SMTP relay or Graph `Mail.Send` limited to startupsupport@buas.nl.
4. **Privacy statement**: the final text approved by BUas's privacy officer, entered under
   *Admin → Privacy statements*; agree on the retention period.
5. **Daily cron** for `retention_check` and the backups above.
6. **Import** the historical sheet(s) on the production server, and point the old Microsoft Form to the new link.

## Project layout

```
buss/          Django project (settings, urls)
siteconfig/    Editable configuration: domains, study years, stages, page texts, privacy statement, closure days, settings
crm/           Coaches, students, startups, registrations, graduation track, activities, follow-ups
crm/workdays.py  Working-day calculation (weekends, Dutch holidays, closure days)
tests/         pytest suite
```
