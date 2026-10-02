# BUSS Startup Support app — plan

## Stack

Django 5.2 LTS (Python 3.11+), server-rendered templates with HTMX and Alpine.js
(vendored, no CDN), PostgreSQL in production / SQLite locally, Docker Compose.
One codebase, one language, built-in admin for configuration, built-in i18n,
mature libraries for audit logging (`django-auditlog`), OIDC/Entra ID
(`mozilla-django-oidc`), Excel (`openpyxl`) and Dutch holidays (`holidays`).

## Decisions from the Q&A

| Topic | Decision |
|---|---|
| Student number | Exactly 6 digits. Optional (but still shown) for "I am an employee". |
| Email | Any valid address accepted; hint when it is not `@buas.nl`. |
| Employees | Still answer study year. |
| Hand-in date | Must be in the future; warning when < 4 weeks away. |
| Intake clock | Stops at **intake scheduled**; held date + coach recorded separately. |
| Working days | Start counting the working day after registration; skip weekends, Dutch public holidays and admin-editable BUas closure days. |
| Coaches | 12 coaches from "Meet the coaches" (incl. Pim Dopheide). Coach domains derived from academy codes. |
| Branding | Placeholder logo; BUas-like palette in CSS variables. |
| Staff email | Placeholder shared mailbox (configurable). In-app notifications as well. |
| Permissions | Coaches: view/edit all records **and** edit form content (page text, option lists, coach profiles). Admin-only: users/roles, merge, delete/anonymise, imports, system settings. |
| Note visibility | All coaches see all notes; optional "admin only" flag per note. |
| Retention | Default 2 years after last activity / alumni, configurable. |
| Startup name / KvK | Staff-only optional fields; fallback title = first words of the description. |
| Delivery | Push each step to the branch; one PR at the end. |

## Entities

**Reference / configuration (`siteconfig`)**
- `Domain` — name, academy code, order, active, `is_employee`.
- `StudyYear` — name, order, active, `is_graduation_track`.
- `PipelineStage` — name, order, colour, `is_initial`, `is_closed`, `counts_as_intake_scheduled`, `counts_as_intake_done`.
- `SiteText` — key, title, body (Markdown). Intro text, notices, thank-you text, coach note…
- `PrivacyStatement` — version, body, published_at. Consent references the exact version.
- `ClosureDay` — date, name (non-working days on top of public holidays).
- `AppSettings` (singleton) — intake working days (10), "due soon" threshold (2), notification mode (email / in-app / both), staff notification email, retention years, inactivity weeks, rate-limit numbers.
- `EmailTemplate` (step 3) — key, subject, body.

**Records (`crm`)**
- `Coach` — user (optional, links to staff login), first/last name, email, academy, home domains (M2M Domain), photo, background, help-with, active, order.
- `Student` — first/last name, student number (6 digits, nullable), email, phone, domain, study year, archived, anonymised_at, merged_into, timestamps.
- `Startup` — name (optional), description, paying customers (Y/N/unknown), validated (Y/N/unknown), goals, stage, assigned coach, tags, KvK number, archived, last_activity_at. Founders = M2M Student through `Founder` (role, joined_on).
- `Registration` — one per form submission / walk-in / import: student, startup, submitted_at, source, preferred coach / no preference, comments, answers snapshot (JSON), consent timestamp + privacy version, Forms response ID, duplicate flag, intake deadline, intake scheduled on, intake held on, intake coach.
- `GraduationTrack` — student, startup, registration, programme approval (yes / not yet), topic, supervisor, intended hand-in date.
- `Tag`, `Activity` (startup, kind, date, author, body, admin_only), `FollowUp` (startup/student, title, due date, assigned user, done_at, created_by, auto-reason), `Notification` (user, text, link, read_at).
- Audit log via `django-auditlog` on all personal-data models.

## Pages

Public: `/register/` (multi-section form), `/register/thanks/`, `/privacy/`.
Staff: intake queue, students, startups (list/board), startup detail with activity log, follow-ups ("my week"), dashboard, exports, Forms import, GDPR tools, notifications. Admin (`/admin/`) for configuration.

## Build order

1. Data model and seed data
2. Public registration form + conditional graduation section
3. Confirmation and staff emails
4. Intake queue
5. Records CRUD
6. Pipeline board
7. Activity log and follow-ups
8. Dashboard
9. Export
10. Forms migration import
11. Staff authentication (Entra ID) and roles
12. GDPR tools

## Later phases (designed for, not built)
- Student login: `Student` gets an optional `user` link; registrations already store everything per student.
- Intake scheduling via Graph: `Registration.intake_scheduled_on` + an `external_event_id` field later.
- Events: `Activity.kind = event` now; a dedicated `Event`/`EventRegistration` model later.
