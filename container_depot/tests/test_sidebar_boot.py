"""Regression test for the desk-boot SessionBootFailed crash.

Frappe's WorkspaceSidebar reads the domain-restricted caches without a lazy-build
fallback; when they are empty (post cache-clear) and the user has no allowed
workspaces, is_item_allowed() does `name in None` and the boot dies. We warm the
caches in a before_request hook so they are never None.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.boot import patch_workspace_sidebar_can_read, warm_domain_restricted_caches


class TestDomainCacheWarm(FrappeTestCase):
	def test_warm_populates_both_caches(self):
		frappe.cache.delete_value("domain_restricted_pages")
		frappe.cache.delete_value("domain_restricted_doctypes")
		warm_domain_restricted_caches()
		self.assertIsNotNone(frappe.cache.get_value("domain_restricted_pages"))
		self.assertIsNotNone(frappe.cache.get_value("domain_restricted_doctypes"))

	def test_workspace_sidebar_restricted_pages_not_none_after_warm(self):
		names = frappe.get_all("Workspace Sidebar", limit=1, pluck="name")
		if not names:
			self.skipTest("no Workspace Sidebar docs on this site")

		# The crash condition: cache empty -> WorkspaceSidebar.restricted_pages is None.
		frappe.cache.delete_value("domain_restricted_pages")
		self.assertIsNone(frappe.get_doc("Workspace Sidebar", names[0]).restricted_pages)

		# After warming, a freshly loaded sidebar sees a real list (no boot crash).
		warm_domain_restricted_caches()
		self.assertIsNotNone(frappe.get_doc("Workspace Sidebar", names[0]).restricted_pages)


class TestSidebarCanRead(FrappeTestCase):
	"""Sidebar kiri yang kosong: satu `return` yang hilang di Frappe, bukan soal izin.

	`WorkspaceSidebar.get_can_read_items` membangun izin user lalu tidak mengembalikan
	apa pun, padahal `__init__` memakai nilai kembaliannya sebagai `self.can_read`.
	`is_item_allowed` lalu menguji `name in (self.can_read or [])`, jadi SETIAP item
	ber-type DocType hilang dari sidebar untuk semua orang kecuali Administrator.
	Kembarannya di `desk/desktop.py` mengembalikan `self.user.can_read` dengan benar, dan
	keduanya berbagi kunci cache — itulah kenapa gejalanya tidak konsisten dan gampang
	salah dibaca sebagai "role-nya belum diberi izin".
	"""

	def test_can_read_is_a_real_list_not_none(self):
		patch_workspace_sidebar_can_read()
		names = frappe.get_all("Workspace Sidebar", limit=1, pluck="name")
		if not names:
			self.skipTest("no Workspace Sidebar docs on this site")
		# Kunci cache dibagi dengan desk/desktop.py: kosongkan dulu, kalau tidak nilai
		# benar yang ditinggalkan jalur itu membuat tes ini lulus tanpa membuktikan apa pun.
		frappe.cache.delete_value("user_perm_can_read", user=frappe.session.user)
		warm_domain_restricted_caches()

		doc = frappe.get_doc("Workspace Sidebar", names[0])
		self.assertIsInstance(doc.can_read, list)
		self.assertTrue(doc.can_read, "daftar kosong = tiap item DocType tersembunyi")

	def test_a_depot_doctype_item_is_visible_to_admin_ops(self):
		"""Gejala yang memicu penelusuran ini: menu master tidak muncul untuk Admin Ops."""
		patch_workspace_sidebar_can_read()
		if not frappe.db.exists("Workspace Sidebar", "Container Depot"):
			self.skipTest("Container Depot sidebar not on this site")
		user = "sidebar-adminops@example.com"
		if frappe.db.exists("User", user):
			frappe.delete_doc("User", user, ignore_permissions=True, force=True)
		doc = frappe.get_doc({
			"doctype": "User", "email": user, "first_name": "Sidebar AO",
			"send_welcome_email": 0, "user_type": "System User",
		}).insert(ignore_permissions=True)
		doc.append("role_profiles", {"role_profile": "Admin Ops"})
		doc.save(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "User", user, ignore_permissions=True, force=True)

		warm_domain_restricted_caches()
		frappe.set_user(user)
		try:
			frappe.cache.delete_value("user_perm_can_read", user=user)
			sidebar = frappe.get_doc("Workspace Sidebar", "Container Depot")
			visible = []
			for item in sidebar.items:
				if item.link_type == "DocType" and sidebar.is_item_allowed(item.link_to, item.link_type, []):
					visible.append(item.link_to)
		finally:
			frappe.set_user("Administrator")

		for doctype in ("Container", "Customer", "Warehouse", "Item", "Depot Contract"):
			with self.subTest(doctype=doctype):
				self.assertIn(doctype, visible)
