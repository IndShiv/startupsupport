# BUSS Startup Support

The registration and coaching app for BUas Business Startup Support (BUSS). It replaces the
Microsoft Form: students register directly in the app, and coaches use the same app to manage
intakes, follow progress and keep notes.

See [docs/PLAN.md](docs/PLAN.md) for the data model, pages and build order.

**Status:** step 1 of 12 is done (data model, seed data, admin). The public form comes next.

## Stack

Django 5.2 LTS · PostgreSQL (production) / SQLite (local) · server-rendered templates · Docker Compose.

## Local development (no Docker)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # optional; defaults work locally
export DJANGO_DEBUG=1
python manage.py migrate
python manage.py seed_demo      # reference data + fake students + dev logins
python manage.py runserver
```

Open http://localhost:8000/admin/ and log in as `admin` or as a coach's first name in lower case
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
| `DJANGO_MEDIA_ROOT` | Where uploaded photos are stored | `./media` |
| `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL` | Email sending (SMTP/Graph come in step 3) | console |

In production, run the app behind a reverse proxy that terminates HTTPS and redirects HTTP to HTTPS.

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
