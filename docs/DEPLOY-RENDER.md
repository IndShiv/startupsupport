# Test server on Render

A test environment for colleagues: **fake data only**, hosted by Render in Frankfurt (EU).
It is defined in [`render.yaml`](../render.yaml): one web service (`buss-test`) and one
PostgreSQL database (`buss-test-db`), both on small paid plans (check render.com/pricing; roughly
$15 a month in total, billed per day, so deleting it stops the cost).

What the test server does differently from a real one (`DEMO_MODE=1`):

- a yellow **"Test environment – do not enter real student details"** banner on every page;
- hidden from search engines (robots.txt, `noindex`);
- fills itself with fake students and startups on the first start;
- staff log in with a username and the password you choose (`DEMO_PASSWORD`), not with Microsoft;
- emails are written to the Render log and never sent.

## 1. Create the server (once, about 15 minutes)

1. Go to **render.com** and sign up (e.g. with your GitHub account). Add a payment card under
   *Billing*; paid plans need one.
2. Choose a password for the testers, at least 12 characters, e.g. three random words. Do **not**
   use `buss-dev-2026`: that one is in the public repository.
3. In Render: **New → Blueprint**. Connect GitHub when asked and pick the repository
   **IndShiv/startupsupport**, branch **claude/vigilant-clarke-5f8i1u**.
4. Render reads `render.yaml` and shows `buss-test` and `buss-test-db`. It asks for one value,
   **DEMO_PASSWORD**: paste the password from step 2. Click **Apply** / **Deploy Blueprint**.
5. The first build takes about 5 minutes. When `buss-test` shows **Live**, its address is at the
   top of the page, e.g. `https://buss-test.onrender.com` (Render may add a few letters).

Check it: open `<address>/register/` (yellow banner) and `<address>/staff/`, log in as `shival`
with your password.

## 2. Logins for testers

| Login | Role |
|---|---|
| `shival` | coach + admin |
| `admin` | admin (not a coach) |
| a coach's first name in lower case: `roeland`, … | coach |

All use the password from step 2. Give each colleague their own coach login, so they see their own
caseload, and send the password separately from the link (e.g. Teams chat vs. email).

To change the password: Render → `buss-test` → *Environment* → edit `DEMO_PASSWORD` → save; then
*Shell* → `python manage.py seed_demo --reset` (this also resets the data, see below).

## 3. Day-to-day

- **Updates**: every change pushed to the branch is deployed automatically (a few minutes; the
  site is briefly slower during the switch).
- **Start fresh** before a test session: Render → `buss-test` → **Shell** →
  ```bash
  python manage.py seed_demo --reset
  ```
  This removes all students, startups and logs (including anything testers typed) and creates new
  fake data. Logins stay.
- **Emails** the app would have sent: Render → `buss-test` → **Logs**.
- **Coach photos** uploaded on the test server disappear on the next deploy (no disk attached).
  That is fine for testing.

## 4. When testing is done

Render → `buss-test-db` → *Settings* → **Delete Database**, and the same for `buss-test`. That
removes everything, including what testers typed.

## Why this is safe enough for a test

- Only fake data: the banner tells testers not to enter real student details, and the data is
  reset regularly.
- Stored in the EU (Frankfurt). The database is not reachable from the internet, only by the app.
- HTTPS, secure cookies and a password that is not in the repository.
- Nothing is emailed and no other service receives data.

It is **not** the production setup: for real student data use BUas hosting with Microsoft sign-in
(see *Go-live* in the README).
