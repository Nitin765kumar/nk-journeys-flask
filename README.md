# NK Journeys (Flask edition)

A full-stack travel booking website built with Flask and SQLite. Visitors browse trips, book, pay through a **simulated** checkout and get a voucher. An admin area manages bookings, enquiries and packages.

> **Demo project.** Payments are simulated. No real money moves and card details are never stored.

The earlier static version (HTML, CSS and JavaScript on GitHub Pages) lives in the `nk-journeys` repository.

## What the server does

| Area | What happens on the server |
| --- | --- |
| Packages | Stored in the database. Filters, search and sorting run in SQL. Each package has its own URL, such as `/packages/kerala-6d`, so Google can index it. |
| Booking | The server validates every field and **recalculates the price itself**. The browser's total is only a preview. |
| Payment | `payments.py` checks the details and decides the outcome. Only the last four digits of a card are kept. |
| Voucher | Private URL with a long random token (`/voucher/<token>`). Booking IDs alone cannot open a voucher. |
| Track booking | Needs the booking ID **and** the mobile number used. |
| Accounts | Customers can register and log in (`/register`, `/login`). A booking made while logged in is linked to the account and listed on `/account` ("My bookings"), and the booking form is pre-filled. Guests can still book without an account. |
| Enquiries | Saved in the database and shown in the admin area. |
| Admin | Login, dashboard, booking status changes, enquiry status, and add or edit packages. |

## Run locally (Windows PowerShell)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
flask --app app run --debug
```

Open http://127.0.0.1:5000. The admin login is at http://127.0.0.1:5000/admin/login (there is also an "Admin login" link in the footer) with the `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`. If `ADMIN_PASSWORD` is empty, a random one is printed in the terminal the first time the database is created.

**Cannot log in?** The server reads `.env` only when it starts. Stop it completely with Ctrl+C and start it again after changing the file (the auto-reload of debug mode is not enough). To see what the server expects, run `flask --app app check-admin`, type the password, and it tells you whether it matches without printing it.

## Demo test values

| Item | Value |
| --- | --- |
| Coupon | `NKJ10` (10% off the trip fare) |
| Card that succeeds | `4111 1111 1111 1111`, any future expiry, any 3-digit CVV |
| Card that is declined | `4000 0000 0000 0002` |
| UPI that is declined | `fail@upi` (any other `name@bank` succeeds) |
| Bank that fails | "Test bank (payment fails)" |

## Run the tests

```powershell
python -m unittest discover -s tests -v
```

The tests cover pages, filters, pricing, booking validation, every payment method, declined payments, voucher privacy, CSRF protection, escaping of user text, the admin login and the admin forms.

## Project structure

```
app.py          App factory and public routes
admin.py        Admin blueprint (login, bookings, enquiries, packages)
accounts.py     Customer accounts: register, log in, log out, My bookings
throttle.py     Limits repeated failed logins (admin and customers)
db.py           SQLite connection, schema loading, sample data, admin account
catalog.py      Queries for destinations and packages
pricing.py      Fare, coupon, GST and advance calculation (integer paise)
payments.py     Simulated payment gateway
helpers.py      Constants, template filters and small utilities
schema.sql      Database tables
data/seed.json  Sample destinations and packages (loaded on first run)
templates/      Jinja templates (templates/admin for the admin area)
static/         CSS, JavaScript, images, favicon and logo
tests/          Automated tests
```

## How a booking flows

1. `/packages/<id>` shows the trip. The booking card sends the date and adults to `/book/<id>`.
2. `POST /book/<id>` validates the form, calculates the price on the server and saves a booking as **Pending payment**. You are redirected to `/pay/<token>`.
3. `POST /pay/<token>` runs the simulated payment. Success marks the booking **Confirmed**. A decline is logged and the booking stays pending, so you can retry.
4. `/voucher/<token>` shows the voucher. The admin can then move the booking to Completed or Cancelled.

## Deploy on Render

1. Push this folder to a new GitHub repository, for example `nk-journeys-flask`.
2. On Render, create a **Web Service** from the repository (or use the included `render.yaml` as a Blueprint).
3. Set the environment variables: `SECRET_KEY` (a long random string), `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SITE_URL` (your Render URL) and `SESSION_COOKIE_SECURE=1`.
4. Start command: `gunicorn "app:create_app()" --workers 1 --bind 0.0.0.0:$PORT`.

**Important about data:** SQLite stores everything in one file. On Render's free plan the disk is temporary, so bookings and enquiries can disappear when the service restarts or redeploys. The packages come back because they are reloaded from `data/seed.json`. To keep bookings you need a persistent disk or a hosted database such as Postgres. Check Render's current plans and documentation, as they change.

## Security notes

- Customer and admin passwords are hashed. Customer emails are **not verified** in this demo, which is why guest bookings are never linked to an account automatically.
- Passwords are hashed. The admin account comes from environment variables, never from the code.
- Every form has a CSRF token. Cookies are `HttpOnly` and `SameSite=Lax`, and `Secure` when `SESSION_COOKIE_SECURE=1`.
- Admin and customer logins are limited to five failed attempts per fifteen minutes. A customer login never opens the admin area, and a login redirect only follows links that stay on this site.
- An older database is upgraded automatically when the app starts (a `user_id` column is added to bookings).
- All SQL uses placeholders. Sort orders come from a whitelist. Package images must be files from `static/img`.
- Templates escape user text, so a name like `<script>` is shown as text.

## Ideas for next steps

- Send real confirmation emails (for example with Flask-Mail or an email API).
- Move to Postgres for persistent data.
- Add a payment gateway in test mode (for example Razorpay).
- Add reviews, a gallery per package and an admin page for destinations.
