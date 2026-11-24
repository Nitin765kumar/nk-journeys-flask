"""NK Journeys: a travel booking site built with Flask and SQLite.

Demo project. Payments are simulated and no real money or card data is handled.
Run it with:  flask --app app run --debug
"""
import hmac
import json
import os
import secrets
from datetime import date, timedelta

import click
from dotenv import load_dotenv
from flask import (Flask, Response, abort, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

import accounts
import catalog
import db
import payments
import pricing
import throttle
from admin import bp as admin_bp
from helpers import (CATEGORIES, DEFAULT_EXCLUSIONS, DEFAULT_INCLUSIONS, EMAIL_RE, PHONE_RE,
                     clamp_int, fmt_date, fmt_datetime, inr, inr_rupees, new_ref)

NAV_LINKS = [("home", "Home"), ("destinations", "Destinations"), ("packages", "Packages"),
             ("about", "About"), ("support", "Support"), ("contact", "Contact")]
PAGES = {"about": "/about", "support": "/support", "privacy": "/privacy", "terms": "/terms",
         "cancellation": "/cancellation", "payment_policy": "/payment-policy"}
MIN_DAYS_AHEAD = 7

# Only our own scripts run. Styles may be inline (the templates use style attributes) and Google Fonts is allowed.
CSP = "; ".join([
    "default-src 'self'",
    "img-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "script-src 'self'",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
])


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DATABASE_PATH=os.environ.get("DATABASE_PATH", os.path.join(app.instance_path, "nkj.db")),
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
        SITE_URL=os.environ.get("SITE_URL", "").rstrip("/"),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
        MAX_CONTENT_LENGTH=64 * 1024,
        SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=30),    # browsers keep CSS, JS and photos for a month
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),   # a signed login cookie stops working after this
        TRUST_PROXY=os.environ.get("TRUST_PROXY") == "1",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        if app.debug or app.testing:
            app.config["SECRET_KEY"] = "dev-only-secret-key"
        else:
            raise RuntimeError("Set the SECRET_KEY environment variable (see .env.example).")

    if app.config["TRUST_PROXY"]:
        # Behind Render's proxy the real visitor IP and the https scheme arrive in X-Forwarded-* headers.
        # Without this every visitor looks like the same address and the login limits would hit everyone.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.teardown_appcontext(db.close_db)
    db.init_db(app)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(accounts.bp)
    app.before_request(accounts.load_user)
    register_template_helpers(app)
    register_security(app)
    register_routes(app)
    register_errors(app)
    register_cli(app)
    return app


# ---------------------------------------------------------------- setup
def site_url():
    """Public base URL: SITE_URL from the environment, otherwise whatever the request used."""
    return current_app.config["SITE_URL"] or request.url_root.rstrip("/")


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def register_template_helpers(app):
    app.jinja_env.filters.update(inr=inr, inr_rupees=inr_rupees, fmt_date=fmt_date,
                                 fmt_datetime=fmt_datetime)
    app.jinja_env.globals["csrf_token"] = csrf_token

    def static_url(filename):
        """URL of a static file with its modified time attached, so a changed CSS or JS file is fetched again."""
        path = os.path.join(current_app.static_folder, filename)
        version = int(os.path.getmtime(path)) if os.path.exists(path) else 0
        return url_for("static", filename=filename, v=version)

    app.jinja_env.globals["static_url"] = static_url

    def url_with(**changes):
        """URL of the current page with some query parameters changed or removed."""
        args = request.args.to_dict()
        args.update(changes)
        args = {k: v for k, v in args.items() if v not in ("", None, "all")}
        return url_for(request.endpoint, **args)

    @app.context_processor
    def inject():
        return {
            "nav_links": NAV_LINKS,
            "categories": CATEGORIES,
            "url_with": url_with,
            "canonical": site_url() + request.path,
            "site_url": site_url(),
            "year": date.today().year,
            "user": g.get("user"),
        }


def register_security(app):
    @app.before_request
    def check_csrf():
        if request.method == "POST":
            sent = request.form.get("csrf_token", "")
            if not hmac.compare_digest(sent, session.get("_csrf", "")):
                abort(400, "Your session expired. Go back, refresh the page and try again.")

    @app.after_request
    def headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Content-Security-Policy", CSP)
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


def register_errors(app):
    def show(code, title, text):
        return render_template("error.html", code=code, title=title, text=text), code

    @app.errorhandler(400)
    def bad_request(e):
        return show(400, "That did not work", getattr(e, "description", "Bad request."))

    @app.errorhandler(404)
    def not_found(e):
        return show(404, "We could not find that page", "The link may be old or mistyped.")

    @app.errorhandler(429)
    def too_many(e):
        return show(429, "Too many requests", getattr(e, "description", "Please slow down and try again later."))

    @app.errorhandler(413)
    def too_large(e):
        return show(413, "That request was too large", "Please shorten your message and try again.")

    @app.errorhandler(500)
    def server_error(e):
        return show(500, "Something went wrong on our side", "Please try again in a moment.")


def register_cli(app):
    @app.cli.command("check-admin")
    @click.option("--password", prompt=True, hide_input=True, help="The password you type on the login page.")
    def check_admin(password):
        """Explain why the admin login works or fails (never prints the password)."""
        username = app.config["ADMIN_USERNAME"]
        from_env = app.config.get("ADMIN_PASSWORD")
        with app.app_context():
            row = db.query("SELECT password_hash FROM admins WHERE username = ?", (username,), one=True)
        click.echo(f"Admin username the server expects: {username}")
        click.echo("ADMIN_PASSWORD from .env or environment: "
                   + (f"set ({len(from_env)} characters)" if from_env else "not set"))
        if row and check_password_hash(row["password_hash"], password):
            click.echo("The password you typed MATCHES the stored admin login.")
        else:
            click.echo("The password you typed does NOT match the stored admin login.")
            click.echo("Check .env, stop the server completely with Ctrl+C, then start it again.")


# ---------------------------------------------------------------- bookings
def booking_by_token(token):
    row = db.query("SELECT * FROM bookings WHERE token = ?", (token,), one=True)
    if row is None:
        abort(404)
    booking = dict(row)
    booking["travellers"] = json.loads(booking["travellers"])
    return booking


def default_travel_date():
    return (date.today() + timedelta(days=21)).isoformat()


def parse_booking_form(form):
    """Validate the booking form. Returns (clean values, list of error messages)."""
    errors = []
    values = {
        "name": form.get("name", "").strip(),
        "phone": form.get("phone", "").strip(),
        "email": form.get("email", "").strip(),
        "city": form.get("city", "").strip(),
        "travel_date": form.get("travel_date", ""),
        "adults": clamp_int(form.get("adults"), 1, pricing.MAX_ADULTS, 2),
        "children": clamp_int(form.get("children"), 0, pricing.MAX_CHILDREN, 0),
        "travellers": [t.strip() for t in form.getlist("traveller")],
        "coupon": form.get("coupon", "").strip().upper(),
        "pay_mode": form.get("pay_mode", "full"),
    }
    if not 2 <= len(values["name"]) <= 80:
        errors.append("Enter the lead traveller's full name.")
    if not PHONE_RE.fullmatch(values["phone"]):
        errors.append("Enter a 10-digit Indian mobile number starting with 6, 7, 8 or 9.")
    if not EMAIL_RE.fullmatch(values["email"]) or len(values["email"]) > 120:
        errors.append("Enter a valid email address.")
    try:
        chosen = date.fromisoformat(values["travel_date"])
        earliest = date.today() + timedelta(days=MIN_DAYS_AHEAD)
        if chosen < earliest or chosen > date.today() + timedelta(days=730):
            raise ValueError
    except ValueError:
        errors.append(f"Pick a travel date at least {MIN_DAYS_AHEAD} days from today.")
    needed = values["adults"] + values["children"] - 1
    others = values["travellers"][:needed]
    if len(others) < needed or any(not 2 <= len(n) <= 80 for n in others):
        errors.append("Enter the name of every traveller.")
    values["travellers"] = others
    if values["coupon"] and not pricing.coupon_percent(values["coupon"]):
        errors.append("That coupon code is not valid. Try NKJ10 in this demo.")
    if values["pay_mode"] not in ("full", "advance"):
        values["pay_mode"] = "full"
    return values, errors


def create_booking(package, v, user_id=None):
    q = pricing.quote(package["price"], v["adults"], v["children"], v["coupon"], v["pay_mode"])
    token = secrets.token_urlsafe(16)
    db.execute(
        "INSERT INTO bookings (ref, token, user_id, package_id, package_name, name, phone, email, city, "
        "travel_date, adults, children, travellers, coupon, pay_mode, base, discount, gst, total, pay_now) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (new_ref("NKJ", 6, "bookings"), token, user_id, package["id"], package["name"], v["name"], v["phone"],
         v["email"], v["city"], v["travel_date"], v["adults"], v["children"],
         json.dumps([v["name"]] + v["travellers"]), v["coupon"], v["pay_mode"],
         q["base"], q["discount"], q["gst"], q["total"], q["pay_now"]),
    )
    return token


def record_payment(booking, result, ok):
    db.execute(
        "INSERT INTO payments (booking_id, payment_id, method, last4, amount, status, reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (booking["id"], "pay_demo_" + secrets.token_hex(5), result.method, result.last4,
         booking["pay_now"], "Success" if ok else "Failed", "" if ok else result.message),
    )


# ---------------------------------------------------------------- routes
def register_routes(app):
    @app.get("/")
    def home():
        stats = {"packages": len(catalog.search_packages()), "destinations": len(catalog.destinations())}
        return render_template("home.html", featured=catalog.featured_packages(3),
                               tiles=catalog.destinations(limit=5), stats=stats)

    @app.get("/destinations")
    def destinations():
        cat, q = request.args.get("cat", ""), request.args.get("q", "").strip()
        return render_template("destinations.html", items=catalog.destinations(cat, q), cat=cat, q=q)

    @app.get("/packages")
    def packages():
        dest_id, cat = request.args.get("dest", ""), request.args.get("cat", "")
        q, sort = request.args.get("q", "").strip(), request.args.get("sort", "pop")
        return render_template("packages.html", items=catalog.search_packages(dest_id, cat, q, sort),
                               dest=catalog.get_destination(dest_id) if dest_id else None,
                               cat=cat, q=q, sort=sort)

    @app.get("/packages/<package_id>")
    def package(package_id):
        item = catalog.get_package(package_id) or abort(404)
        return render_template(
            "package.html", p=item, dest=catalog.get_destination(item["dest_id"]),
            inclusions=item["inclusions"] or DEFAULT_INCLUSIONS,
            exclusions=item["exclusions"] or DEFAULT_EXCLUSIONS,
            default_date=default_travel_date(),
            min_date=(date.today() + timedelta(days=MIN_DAYS_AHEAD)).isoformat())

    @app.route("/book/<package_id>", methods=["GET", "POST"])
    def book(package_id):
        item = catalog.get_package(package_id) or abort(404)
        errors = []
        if request.method == "POST":
            throttle.rate_limit("book", 20)
            values, errors = parse_booking_form(request.form)
            if not errors:
                return redirect(url_for("pay", token=create_booking(item, values, g.user["id"] if g.user else None)))
        else:
            me = g.user
            values = {"name": me["name"] if me else "", "phone": me["phone"] if me else "",
                      "email": me["email"] if me else "", "city": "",
                      "travel_date": request.args.get("date") or default_travel_date(),
                      "adults": clamp_int(request.args.get("adults"), 1, pricing.MAX_ADULTS, 2),
                      "children": 0, "travellers": [], "coupon": "", "pay_mode": "full"}
        quote = pricing.quote(item["price"], values["adults"], values["children"],
                              values["coupon"], values["pay_mode"])
        page = render_template(
            "book.html", p=item, v=values, errors=errors, quote=quote, coupons=pricing.COUPONS,
            min_date=(date.today() + timedelta(days=MIN_DAYS_AHEAD)).isoformat(),
            max_adults=pricing.MAX_ADULTS, max_children=pricing.MAX_CHILDREN)
        return (page, 400) if errors else page

    @app.route("/pay/<token>", methods=["GET", "POST"])
    def pay(token):
        booking = booking_by_token(token)
        if booking["status"] in ("Confirmed", "Completed"):
            return redirect(url_for("voucher", token=token))
        if booking["status"] == "Cancelled":
            abort(404)
        error, active, code = "", request.form.get("method", "upi"), 200
        if request.method == "POST":
            result = payments.process(active, request.form)
            if result.ok:
                record_payment(booking, result, True)
                db.execute("UPDATE bookings SET status = 'Confirmed' WHERE id = ? AND status = 'Pending payment'",
                           (booking["id"],))
                return redirect(url_for("voucher", token=token))
            if result.declined:
                record_payment(booking, result, False)
            error, code = result.message, (200 if result.declined else 400)
        return render_template("pay.html", b=booking, error=error, active=active,
                               banks=payments.BANKS, wallets=payments.WALLETS), code

    @app.get("/voucher/<token>")
    def voucher(token):
        booking = booking_by_token(token)
        if booking["status"] == "Pending payment":
            return redirect(url_for("pay", token=token))
        payment = db.query("SELECT * FROM payments WHERE booking_id = ? AND status = 'Success' "
                           "ORDER BY id DESC LIMIT 1", (booking["id"],), one=True)
        due = date.fromisoformat(booking["travel_date"]) - timedelta(days=MIN_DAYS_AHEAD)
        return render_template("voucher.html", b=booking, payment=payment, due=due.isoformat(),
                               balance=booking["total"] - booking["pay_now"])

    @app.post("/track")
    def track():
        key = ("track", request.remote_addr or "unknown")
        if throttle.blocked(key):
            flash("Too many attempts. Please try again in a few minutes.", "error")
            return redirect(url_for("support") + "#track")
        ref = request.form.get("ref", "").strip().upper()
        phone = request.form.get("phone", "").strip()
        row = db.query("SELECT token, phone, status FROM bookings WHERE ref = ?", (ref,), one=True)
        if row and hmac.compare_digest(row["phone"], phone):
            return redirect(url_for("voucher", token=row["token"]))
        throttle.fail(key)
        flash("No booking matches that ID and mobile number. Check both and try again.", "error")
        return redirect(url_for("support") + "#track")

    @app.route("/contact", methods=["GET", "POST"])
    def contact():
        form = {"name": "", "email": "", "phone": "", "trip": request.args.get("trip", "Custom trip"),
                "travel_when": "", "message": ""}
        trips = ["Custom trip"] + [p["name"] for p in catalog.search_packages()]
        if request.method == "POST":
            throttle.rate_limit("contact", 10)
            form = {k: request.form.get(k, "").strip() for k in form}
            errors = []
            if not 2 <= len(form["name"]) <= 80:
                errors.append("Enter your name.")
            if not EMAIL_RE.fullmatch(form["email"]):
                errors.append("Enter a valid email address.")
            if form["phone"] and not PHONE_RE.fullmatch(form["phone"]):
                errors.append("Enter a 10-digit mobile number, or leave it empty.")
            if not 10 <= len(form["message"]) <= 2000:
                errors.append("Tell us a little more in your message (at least 10 characters).")
            if form["trip"] not in trips:
                form["trip"] = "Custom trip"
            if not errors:
                ref = new_ref("ENQ", 5, "enquiries")
                db.execute("INSERT INTO enquiries (ref, name, email, phone, trip, travel_when, message) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (ref, form["name"], form["email"], form["phone"], form["trip"],
                            form["travel_when"][:80], form["message"]))
                flash(f"Thanks, {form['name']}. Your enquiry ID is {ref}. We will reply within one working day.", "ok")
                return redirect(url_for("contact"))
            return render_template("contact.html", form=form, trips=trips, errors=errors), 400
        return render_template("contact.html", form=form, trips=trips, errors=[])

    def static_page(endpoint, template):
        app.add_url_rule(PAGES[endpoint], endpoint, lambda: render_template(template))

    for endpoint in PAGES:
        static_page(endpoint, endpoint.replace("_", "-") + ".html")

    @app.get("/sitemap.xml")
    def sitemap():
        urls = [url_for(e) for e in ("home", "destinations", "packages", "about", "support", "contact",
                                      "privacy", "terms", "cancellation", "payment_policy")]
        urls += [url_for("package", package_id=p["id"]) for p in catalog.search_packages()]
        body = "".join(f"  <url><loc>{site_url()}{u}</loc></url>\n" for u in urls)
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n')
        return Response(xml, mimetype="application/xml")

    @app.get("/robots.txt")
    def robots():
        text = ("User-agent: *\nDisallow: /admin\nDisallow: /pay/\nDisallow: /voucher/\nDisallow: /book/\n"
                f"Sitemap: {site_url()}/sitemap.xml\n")
        return Response(text, mimetype="text/plain")


if __name__ == "__main__":
    create_app().run(debug=True)
