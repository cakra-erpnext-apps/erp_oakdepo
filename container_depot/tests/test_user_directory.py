"""Siapa yang boleh mencari User: daftar, picker, awesomebar, `@sebutan`.

Dua akun uji: satu staf biasa (izinnya cuma `select`) dan satu akun portal (staf + satu
User Permission `Customer`). Yang pertama kehilangan daftar tapi tetap punya picker; yang
kedua kehilangan semuanya kecuali dirinya sendiri.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

_USER = "zz.user-directory@example.com"
_PORTAL = "zz.user-directory-portal@example.com"


class TestUserDirectory(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for email, name in ((_USER, "ZZ User Directory"), (_PORTAL, "ZZ User Directory Portal")):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": name,
						"send_welcome_email": 0,
					}
				).insert(ignore_permissions=True)
		cls.customer = frappe.get_all("Customer", limit=1, pluck="name")
		if cls.customer:
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": _PORTAL,
					"allow": "Customer",
					"for_value": cls.customer[0],
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for name in frappe.get_all("User Permission", filters={"user": _PORTAL}, pluck="name"):
			frappe.delete_doc("User Permission", name, force=1, ignore_permissions=True)
		for email in (_USER, _PORTAL):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()

	def _names(self, user, cmd):
		frappe.set_user(user)
		frappe.local.form_dict = frappe._dict({"cmd": cmd})
		return frappe.get_list("User", pluck="name", limit_page_length=0)

	def test_list_view_sees_only_itself(self):
		self.assertTrue(frappe.only_has_select_perm("User", user=_USER), "fixture lost its role model")
		self.assertEqual(self._names(_USER, "frappe.desk.reportview.get"), [_USER])

	def test_link_picker_is_untouched(self):
		"""Assign To / Share / mention all read through search_link — narrowing it breaks them."""
		names = self._names(_USER, "frappe.desk.search.search_link")
		# `Administrator` never shows up for anyone else (frappe's own `User.has_permission`
		# hides the standard users), so the test is "somebody besides me".
		self.assertTrue([n for n in names if n != _USER], "picker came back empty")

	def test_a_user_with_read_permission_is_untouched(self):
		self.assertGreater(len(self._names("Administrator", "frappe.desk.reportview.get")), 1)

	def test_portal_account_loses_the_picker_too(self):
		"""Akun customer tidak punya pekerjaan yang perlu memilih pegawai OAK."""
		if not self.customer:
			self.skipTest("site has no Customer to tie a portal account to")
		for cmd in (
			"frappe.desk.reportview.get",
			"frappe.desk.search.search_link",
			"frappe.desk.search.search_widget",
		):
			with self.subTest(cmd=cmd):
				self.assertEqual(self._names(_PORTAL, cmd), [_PORTAL])

	def test_portal_account_has_no_mentions(self):
		from container_depot.user_directory import get_names_for_mentions

		if not self.customer:
			self.skipTest("site has no Customer to tie a portal account to")
		frappe.set_user(_PORTAL)
		self.assertEqual(get_names_for_mentions("a"), [])
		frappe.set_user(_USER)
		self.assertTrue(get_names_for_mentions("a"), "staff lost their mention list")

	def test_awesomebar_is_a_list_not_a_picker(self):
		self.assertEqual(self._names(_USER, "frappe.desk.search.search_widget"), [_USER])
