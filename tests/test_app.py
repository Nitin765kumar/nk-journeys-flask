"""End-to-end tests for NK Journeys. Run with:  python -m unittest discover -s tests -v"""
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
import pricing  # noqa: E402
from app import create_app  # noqa: E402

TRAVEL_DATE = (date.today() + timedelta(days=30)).isoformat()


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True, "SECRET_KEY": "test-secret", "ADMIN_PASSWORD": "pw-for-tests",
            "DATABASE_PATH": os.path.join(self.tmp.name, "test.db"),
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, url, data=None, **kwargs):
        """POST with a valid CSRF token, as a browser would after loading a form."""
        with self.client.session_transaction() as s:
            s.setdefault("_csrf", "token-for-tests")
            token = s["_csrf"]
        return self.client.post(url, data={**(data or {}), "csrf_token": token}, **kwargs)

    def query(self, sql, args=()):
        with self.app.app_context():
            return [dict(r) for r in db.query(sql, args)]

    def booking_form(self, **overrides):
        data = {"name": "Asha Verma", "phone": "9876543210", "email": "asha@example.com", "city": "Delhi",
                "travel_date": TRAVEL_DATE, "adults": "2", "children": "0", "traveller": ["Ravi Verma"],
                "coupon": "", "pay_mode": "full"}
        data.update(overrides)
        return data

    def make_booking(self, package="kerala-6d", **overrides):
        response = self.post(f"/book/{package}", self.booking_form(**overrides))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:400])
        return response.headers["Location"].rsplit("/", 1)[1]        # the private token

    def pay_card(self, token, number="4111 1111 1111 1111", cvv="123"):
        return self.post(f"/pay/{token}", {"method": "card", "card_number": number, "card_name": "Asha Verma",
                                           "card_expiry": "12/35", "card_cvv": cvv})

    def admin_login(self):
        response = self.post("/admin/login", {"username": "admin", "password": "pw-for-tests"})
        self.assertEqual(response.status_code, 302)


class PublicPages(AppTestCase):
    def test_pages_load(self):
        for url in ["/", "/destinations", "/packages", "/packages/kerala-6d", "/about", "/support", "/contact",
                    "/privacy", "/terms", "/cancellation", "/payment-policy", "/sitemap.xml", "/robots.txt"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_unknown_pages_are_404(self):
        self.assertEqual(self.client.get("/packages/nope").status_code, 404)
        self.assertEqual(self.client.get("/voucher/not-a-token").status_code, 404)
        self.assertIn("could not find", self.client.get("/nowhere").get_data(as_text=True))

    def test_filters_and_sorting(self):
        html = self.client.get("/packages?dest=kerala").get_data(as_text=True)
        self.assertIn("Backwaters and Ayurveda", html)
        self.assertNotIn("Golden Triangle", html)
        spiritual = self.client.get("/packages?cat=spiritual").get_data(as_text=True)
        self.assertIn("Ayodhya Darshan", spiritual)
        self.assertNotIn("Goa Beach Break", spiritual)
        cheapest = self.client.get("/packages?sort=lo").get_data(as_text=True)
        self.assertLess(cheapest.index("Ayodhya Darshan"), cheapest.index("Leh, Nubra and Pangong"))

    def test_sitemap_lists_packages(self):
        xml = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("/packages/kerala-6d", xml)
        self.assertNotIn("/admin", xml)

    def test_static_files_are_cached_and_versioned(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertRegex(page, r"/static/css/nkj\.css\?v=\d+")
        response = self.client.get("/static/css/nkj.css")
        self.assertIn("max-age=2592000", response.headers["Cache-Control"])
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_photos_are_responsive(self):
        page = self.client.get("/packages").get_data(as_text=True)
        self.assertIn("kerala-480.webp 480w", page)
        for name in ("kerala-480.webp", "kerala-800.webp", "kerala-1200.webp", "founder-264.webp"):
            response = self.client.get(f"/static/img/{name}")
            self.assertEqual(response.status_code, 200, name)
            response.close()

    def test_home_has_seo_tags(self):
        html = self.client.get("/").get_data(as_text=True)
        for tag in ('rel="canonical"', 'property="og:title"', 'rel="icon"'):
            self.assertIn(tag, html)


class Pricing(unittest.TestCase):
    def test_quote_matches_the_site(self):
        q = pricing.quote(24500, 2, 0, "NKJ10", "advance")
        self.assertEqual((q["base"], q["discount"], q["gst"], q["total"], q["pay_now"]),
                         (4900000, 490000, 220500, 4630500, 1389150))

    def test_children_pay_half(self):
        self.assertEqual(pricing.quote(10000, 1, 2)["base"], 2000000)

    def test_unknown_coupon_gives_nothing(self):
        self.assertEqual(pricing.quote(10000, 1, 0, "WRONG")["discount"], 0)


class Booking(AppTestCase):
    def test_validation_errors(self):
        bad = self.booking_form(phone="123", email="nope", travel_date=date.today().isoformat(), traveller=[""])
        response = self.post("/book/kerala-6d", bad)
        self.assertEqual(response.status_code, 400)
        text = response.get_data(as_text=True)
        for message in ("10-digit", "valid email", "at least 7 days", "name of every traveller"):
            self.assertIn(message, text)
        self.assertEqual(self.query("SELECT * FROM bookings"), [])

    def test_bad_coupon_is_rejected(self):
        self.assertEqual(self.post("/book/kerala-6d", self.booking_form(coupon="FREE100")).status_code, 400)

    def test_server_calculates_the_price(self):
        self.make_booking(coupon="nkj10", pay_mode="advance")
        row = self.query("SELECT * FROM bookings")[0]
        self.assertEqual((row["total"], row["pay_now"], row["status"]), (4630500, 1389150, "Pending payment"))
        self.assertEqual(row["travellers"], '["Asha Verma", "Ravi Verma"]')

    def test_booking_hidden_package_is_404(self):
        self.admin_login()
        self.post("/admin/packages/kerala-6d/edit", self.admin_package_form("kerala-6d", active=""))
        self.assertEqual(self.client.get("/packages/kerala-6d").status_code, 404)

    def admin_package_form(self, package_id, **overrides):
        data = {"name": "Backwaters and Ayurveda", "dest_id": "kerala", "days": "6", "nights": "5", "price": "24500",
                "cats": ["beaches"], "img": "kerala.jpg", "summary": "Houseboat night and tea hills.",
                "highlights": "Houseboat night", "itinerary": "Arrive | Pickup and check-in", "active": "1"}
        data.update(overrides)
        return data


class Payment(AppTestCase):
    def test_declined_card_is_recorded_and_booking_stays_pending(self):
        token = self.make_booking()
        response = self.pay_card(token, "4000 0000 0000 0002")
        self.assertIn("declined", response.get_data(as_text=True))
        self.assertEqual(self.query("SELECT status FROM payments")[0]["status"], "Failed")
        self.assertEqual(self.query("SELECT status FROM bookings")[0]["status"], "Pending payment")

    def test_invalid_card_is_not_recorded(self):
        token = self.make_booking()
        response = self.pay_card(token, "1234 5678 9012 3456")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.query("SELECT * FROM payments"), [])

    def test_successful_payment_confirms_booking(self):
        token = self.make_booking()
        response = self.pay_card(token)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.query("SELECT status FROM bookings")[0]["status"], "Confirmed")
        payment = self.query("SELECT * FROM payments")[0]
        self.assertEqual((payment["status"], payment["last4"]), ("Success", "1111"))
        voucher = self.client.get(f"/voucher/{token}").get_data(as_text=True)
        self.assertIn("Booking confirmed", voucher)
        self.assertNotIn("4111", voucher)                     # the full number is never stored or shown
        self.assertEqual(self.client.get(f"/pay/{token}").status_code, 302)   # already paid

    def test_card_details_are_never_stored(self):
        self.pay_card(self.make_booking(), cvv="739")
        for table in ("payments", "bookings"):
            for row in self.query(f"SELECT * FROM {table}"):
                values = [str(v) for v in row.values()]
                self.assertNotIn("4111111111111111", values)
                self.assertNotIn("4111 1111 1111 1111", values)
                self.assertNotIn("739", values)

    def test_upi_and_wallet_and_bank(self):
        for data, status in [({"method": "upi", "upi": "asha@okbank"}, "Confirmed"),
                             ({"method": "wl", "wallet": "Paytm"}, "Confirmed"),
                             ({"method": "nb", "bank": "HDFC Bank"}, "Confirmed")]:
            token = self.make_booking()
            self.assertEqual(self.post(f"/pay/{token}", data).status_code, 302)
        self.assertEqual({r["status"] for r in self.query("SELECT status FROM bookings")}, {"Confirmed"})

    def test_failing_upi_and_bank(self):
        token = self.make_booking()
        self.assertEqual(self.post(f"/pay/{token}", {"method": "upi", "upi": "fail@upi"}).status_code, 200)
        self.assertEqual(self.post(f"/pay/{token}", {"method": "nb", "bank": "Test bank (payment fails)"}).status_code, 200)
        self.assertEqual(len(self.query("SELECT * FROM payments WHERE status = 'Failed'")), 2)


class TrackingAndSafety(AppTestCase):
    def test_track_needs_matching_phone(self):
        token = self.make_booking()
        self.pay_card(token)
        ref = self.query("SELECT ref FROM bookings")[0]["ref"]
        ok = self.post("/track", {"ref": ref.lower(), "phone": "9876543210"})
        self.assertIn(f"/voucher/{token}", ok.headers["Location"])
        wrong = self.post("/track", {"ref": ref, "phone": "9999999999"})
        self.assertIn("/support", wrong.headers["Location"])

    def test_post_without_csrf_token_is_rejected(self):
        response = self.client.post("/contact", data={"name": "x"})
        self.assertEqual(response.status_code, 400)

    def test_user_text_is_escaped(self):
        token = self.make_booking(name="<script>alert(1)</script>")
        self.pay_card(token)
        html = self.client.get(f"/voucher/{token}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_security_headers(self):
        headers = self.client.get("/").headers
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")


class AdminCheckCommand(AppTestCase):
    def run_check(self, password):
        return self.app.test_cli_runner().invoke(args=["check-admin", "--password", password]).output

    def test_reports_match_and_mismatch(self):
        self.assertIn("MATCHES", self.run_check("pw-for-tests"))
        wrong = self.run_check("not-the-password")
        self.assertIn("does NOT match", wrong)
        self.assertNotIn("pw-for-tests", wrong)          # the real password is never printed


class Accounts(AppTestCase):
    def register(self, **overrides):
        data = {"name": "Meera Shah", "email": "Meera@Example.com", "phone": "9123456780",
                "password": "correct-horse", "confirm": "correct-horse"}
        data.update(overrides)
        return self.post("/register", data)

    def test_nav_shows_login_and_register_when_logged_out(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn(">Log in</a>", page)
        self.assertIn(">Register</a>", page)
        self.assertNotIn("My bookings", page)

    def test_register_logs_in_and_shows_account(self):
        self.assertEqual(self.register().status_code, 302)
        page = self.client.get("/account").get_data(as_text=True)
        self.assertIn("Hello, Meera Shah", page)
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn("My bookings", home)
        self.assertIn("Log out", home)
        row = self.query("SELECT email, password_hash FROM users")[0]
        self.assertEqual(row["email"], "meera@example.com")           # stored lower case
        self.assertNotIn("correct-horse", row["password_hash"])         # only a hash is stored

    def test_register_validation(self):
        for overrides, message in [({"password": "short", "confirm": "short"}, "at least 8"),
                                   ({"confirm": "different-one"}, "do not match"),
                                   ({"phone": "123"}, "10-digit"), ({"email": "nope"}, "valid email")]:
            response = self.register(**overrides)
            self.assertEqual(response.status_code, 400)
            self.assertIn(message, response.get_data(as_text=True))
        self.assertEqual(self.query("SELECT * FROM users"), [])

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.register()
        self.client.post("/logout", data={})
        other = self.app.test_client()
        with other.session_transaction() as s:
            s["_csrf"] = "t"
        response = other.post("/register", data={"name": "Someone", "email": "MEERA@example.com", "phone": "9123456780",
                                                  "password": "another-pass1", "confirm": "another-pass1", "csrf_token": "t"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.get_data(as_text=True))

    def test_login_and_logout(self):
        self.register()
        self.post("/logout")
        self.assertEqual(self.client.get("/account").status_code, 302)
        self.assertEqual(self.post("/login", {"email": "meera@example.com", "password": "wrong-pass"}).status_code, 401)
        self.assertEqual(self.post("/login", {"email": "nobody@example.com", "password": "wrong-pass"}).status_code, 401)
        self.assertEqual(self.post("/login", {"email": "MEERA@example.com", "password": "correct-horse"}).status_code, 302)
        self.assertEqual(self.client.get("/account").status_code, 200)
        self.post("/logout")
        self.assertEqual(self.client.get("/account").status_code, 302)

    def test_login_is_rate_limited(self):
        self.register()
        self.post("/logout")
        for _ in range(5):
            self.post("/login", {"email": "meera@example.com", "password": "wrong-pass"})
        self.assertEqual(self.post("/login", {"email": "meera@example.com", "password": "correct-horse"}).status_code, 429)

    def test_login_redirect_stays_on_site(self):
        self.register()
        self.post("/logout")
        for target, expected in [("/packages", "/packages"), ("https://evil.example", "/account"), ("//evil.example", "/account")]:
            response = self.post("/login?next=" + target, {"email": "meera@example.com", "password": "correct-horse"})
            self.assertTrue(response.headers["Location"].endswith(expected), (target, response.headers["Location"]))
            self.post("/logout")

    def test_customer_login_does_not_open_admin(self):
        self.register()
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_booking_while_logged_in_is_linked_and_prefilled(self):
        self.register()
        form = self.client.get("/book/kerala-6d").get_data(as_text=True)
        self.assertIn("Meera Shah", form)
        self.assertIn("meera@example.com", form)
        self.make_booking(name="Meera Shah", phone="9123456780")
        self.assertIsNotNone(self.query("SELECT user_id FROM bookings")[0]["user_id"])
        page = self.client.get("/account").get_data(as_text=True)
        self.assertIn("Backwaters and Ayurveda", page)
        self.assertIn("Complete payment", page)

    def test_guest_bookings_stay_unlinked_and_other_users_see_nothing(self):
        guest = self.make_booking()
        self.assertIsNone(self.query("SELECT user_id FROM bookings")[0]["user_id"])
        self.register()
        self.assertNotIn("Backwaters", self.client.get("/account").get_data(as_text=True))
        self.assertEqual(self.client.get(f"/pay/{guest}").status_code, 200)   # guest flow still works

    def test_old_database_is_upgraded(self):
        import sqlite3
        path = os.path.join(self.tmp.name, "old.db")
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE bookings (id INTEGER PRIMARY KEY, ref TEXT)")
        conn.commit()
        conn.close()
        create_app({"TESTING": True, "SECRET_KEY": "x", "DATABASE_PATH": path})
        columns = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(bookings)")]
        self.assertIn("user_id", columns)


class Hardening(AppTestCase):
    def test_csp_and_no_inline_scripts(self):
        response = self.client.get("/")
        policy = response.headers["Content-Security-Policy"]
        for part in ("script-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "form-action 'self'"):
            self.assertIn(part, policy)
        for url in ("/", "/packages", "/packages/kerala-6d", "/book/kerala-6d", "/contact", "/login", "/register", "/about", "/admin/login"):
            html = self.client.get(url).get_data(as_text=True)
            self.assertNotIn("onload=", html, url)
            self.assertNotIn("onerror=", html, url)
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)", url)          # every script is an external file

    def test_hsts_only_over_https(self):
        self.assertNotIn("Strict-Transport-Security", self.client.get("/").headers)
        self.assertIn("Strict-Transport-Security", self.client.get("/", base_url="https://localhost").headers)

    def test_contact_form_is_rate_limited(self):
        data = {"name": "Spam", "email": "spam@example.com", "message": "short"}
        codes = [self.post("/contact", data).status_code for _ in range(11)]
        self.assertEqual(codes[:10], [400] * 10)
        self.assertEqual(codes[10], 429)

    def test_track_is_rate_limited(self):
        for _ in range(5):
            self.post("/track", {"ref": "NKJ000000", "phone": "9999999999"})
        page = self.post("/track", {"ref": "NKJ000000", "phone": "9999999999"}, follow_redirects=True)
        self.assertIn("Too many attempts", page.get_data(as_text=True))

    def test_admin_session_expires(self):
        self.admin_login()
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        with self.client.session_transaction() as s:
            s["admin_at"] -= 3 * 60 * 60
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_behind_a_proxy_each_visitor_has_their_own_limit(self):
        proxied = create_app({"TESTING": True, "SECRET_KEY": "x", "ADMIN_PASSWORD": "pw-for-tests", "TRUST_PROXY": True,
                              "DATABASE_PATH": os.path.join(self.tmp.name, "proxy.db")})
        client = proxied.test_client()

        def login(ip, password):
            with client.session_transaction() as s:
                s["_csrf"] = "t"
            return client.post("/admin/login", data={"username": "admin", "password": password, "csrf_token": "t"},
                               headers={"X-Forwarded-For": ip}).status_code
        for _ in range(5):
            self.assertEqual(login("1.1.1.1", "wrong"), 401)
        self.assertEqual(login("1.1.1.1", "pw-for-tests"), 429)       # the attacker is locked out
        self.assertEqual(login("2.2.2.2", "pw-for-tests"), 302)       # the real admin is not


class Contact(AppTestCase):
    def test_enquiry_is_saved(self):
        response = self.post("/contact", {"name": "Meera", "email": "meera@example.com", "phone": "",
                                          "trip": "Custom trip", "travel_when": "March", "message": "Need a Kerala plan for four."},
                             follow_redirects=True)
        self.assertIn("Your enquiry ID is ENQ", response.get_data(as_text=True))
        self.assertEqual(self.query("SELECT name FROM enquiries")[0]["name"], "Meera")

    def test_invalid_enquiry(self):
        response = self.post("/contact", {"name": "", "email": "bad", "message": "short"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.query("SELECT * FROM enquiries"), [])


class Admin(AppTestCase):
    def test_requires_login(self):
        for url in ("/admin/", "/admin/bookings", "/admin/enquiries", "/admin/packages", "/admin/packages/new"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/admin/login", response.headers["Location"])

    def test_admin_link_is_in_the_footer(self):
        self.assertIn("Admin login", self.client.get("/").get_data(as_text=True))
        self.admin_login()
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("Admin dashboard", page)
        self.assertIn(">Admin</a>", page)

    def test_login(self):
        self.assertEqual(self.post("/admin/login", {"username": "admin", "password": "wrong"}).status_code, 401)
        self.admin_login()
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_login_is_rate_limited(self):
        for _ in range(5):
            self.post("/admin/login", {"username": "admin", "password": "wrong"})
        self.assertEqual(self.post("/admin/login", {"username": "admin", "password": "pw-for-tests"}).status_code, 429)

    def test_manage_booking_status_and_enquiry(self):
        self.pay_card(self.make_booking())
        self.post("/contact", {"name": "Meera", "email": "meera@example.com", "message": "Need a Kerala plan for four."})
        self.admin_login()
        booking_id = self.query("SELECT id FROM bookings")[0]["id"]
        self.assertIn("Asha Verma", self.client.get(f"/admin/bookings/{booking_id}").get_data(as_text=True))
        self.post(f"/admin/bookings/{booking_id}/status", {"status": "Cancelled"})
        self.assertEqual(self.query("SELECT status FROM bookings")[0]["status"], "Cancelled")
        self.assertEqual(self.post(f"/admin/bookings/{booking_id}/status", {"status": "Hacked"}).status_code, 400)
        enquiry_id = self.query("SELECT id FROM enquiries")[0]["id"]
        self.post(f"/admin/enquiries/{enquiry_id}/status", {"status": "Closed"})
        self.assertEqual(self.query("SELECT status FROM enquiries")[0]["status"], "Closed")
        self.assertIn("Asha", self.client.get("/admin/bookings?q=Asha").get_data(as_text=True))

    def test_create_and_edit_package(self):
        self.admin_login()
        form = {"id": "goa-3d", "name": "Quick Goa", "dest_id": "goa", "days": "3", "nights": "2", "price": "9999",
                "cats": ["beaches"], "img": "goa.avif", "summary": "A short beach break in Goa.",
                "highlights": "Baga beach\nOld Goa", "itinerary": "Arrive | Check in\nBeach day | Baga and Anjuna",
                "featured": "1", "active": "1"}
        self.assertEqual(self.post("/admin/packages/new", form).status_code, 302)
        page = self.client.get("/packages/goa-3d")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Quick Goa", page.get_data(as_text=True))
        self.assertEqual(self.post("/admin/packages/new", form).status_code, 400)          # duplicate id
        form.update(name="Quick Goa Deluxe", price="12999")
        self.post("/admin/packages/goa-3d/edit", form)
        self.assertEqual(self.query("SELECT price FROM packages WHERE id = 'goa-3d'")[0]["price"], 12999)
        bad = dict(form, price="5", itinerary="no separator here")
        self.assertEqual(self.post("/admin/packages/goa-3d/edit", bad).status_code, 400)

    def test_only_listed_images_are_accepted(self):
        self.admin_login()
        form = {"id": "x-trip", "name": "X trip", "dest_id": "goa", "days": "3", "nights": "2", "price": "9999",
                "img": "../../etc/passwd", "summary": "A short beach break.", "highlights": "One", "itinerary": "A | B"}
        self.assertEqual(self.post("/admin/packages/new", form).status_code, 400)


if __name__ == "__main__":
    unittest.main()
