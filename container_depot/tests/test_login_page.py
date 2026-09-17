"""www/login.html adalah fork tampilan dari halaman login Frappe, tapi logikanya
tetap milik frappe/templates/includes/login/login.js. Yang menyatukan keduanya cuma
konvensi: nama section, id field, dan beberapa class yang dicari jQuery.

Tes ini menjaga kedua sisi sambungan itu — halaman kita masih memuat semuanya, dan
login.js masih mencarinya. Kalau upgrade Frappe mengganti salah satu nama, di
browser gejalanya cuma "tombol tidak bereaksi" atau layar putih setelah klik
"Forgot password?"; di sini jadi kegagalan tes yang menyebut namanya.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import set_request
from frappe.website.serve import get_response_content

# Dicari login.js lewat jQuery; hilang dari halaman = fitur mati diam-diam.
SELECTORS = (
	"for-login",
	"for-forgot",
	"for-signup",
	"form-login",
	"form-forgot",
	"login_email",
	"login_password",
	"forgot_email",
	"login-content page-card",  # dipakai login.set_invalid
	"page-card-body",  # ditandai merah saat kredensial ditolak
	"btn-primary",  # tempat login.set_status menulis "Verifying…"
	"oak_remember_me",  # dicari public/js/login_remember.js
)


class TestLoginPage(FrappeTestCase):
	def setUp(self):
		self._user = frappe.session.user
		frappe.set_user("Guest")
		frappe.local.request_ip = "127.0.0.1"

	def tearDown(self):
		frappe.set_user(self._user)

	def test_page_keeps_every_hook_login_js_needs(self):
		set_request(method="GET", path="/login")
		html = get_response_content("/login")

		self.assertIn("oak-login", html)  # memang halaman kita, bukan bawaan Frappe
		for selector in SELECTORS:
			self.assertIn(selector, html, f"login.html kehilangan '{selector}'")

	def test_login_js_still_looks_for_the_same_names(self):
		path = frappe.get_app_path("frappe", "templates", "includes", "login", "login.js")
		with open(path) as f:
			js = f.read()

		for name in ("#login_email", "#login_password", "#forgot_email", ".form-login", ".for-forgot"):
			self.assertIn(name, js, f"login.js Frappe tidak lagi memakai '{name}' — cek www/login.html")
