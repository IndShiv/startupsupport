# BUSS Startup Support

The registration and coaching app for BUas Business Startup Support (BUSS). It replaces the
Microsoft Form: students register directly in the app, and coaches use the same app to manage
intakes, follow progress and keep notes.

See [docs/PLAN.md](docs/PLAN.md) for the data model, pages and build order.

**Status:** steps 1–5 of 12 are done (data model, seed data, admin, public registration form, emails, intake queue, student and startup records). The pipeline board comes next.

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
| `SITE_URL` | Public address, used for links and the logo in emails | `http://localhost:8000` |
| `EMAIL_PROVIDER` | `console`, `smtp` or `graph` | `console` |
| `DEFAULT_FROM_EMAIL`, `EMAIL_REPLY_TO` | Sender and reply-to address | `startupsupport@buas.nl` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL` | SMTP settings | port 587, TLS on |
| `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `GRAPH_SENDER` | Microsoft Graph sender | sender `startupsupport@buas.nl` |

In production, run the app behind a reverse proxy that terminates HTTPS and redirects HTTP to HTTPS.

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

## Project layout

```
buss/          Django project (settings, urls)
siteconfig/    Editable configuration: domains, study years, stages, page texts, privacy statement, closure days, settings
crm/           Coaches, students, startups, registrations, graduation track, activities, follow-ups
crm/workdays.py  Working-day calculation (weekends, Dutch holidays, closure days)
tests/         pytest suite
```
