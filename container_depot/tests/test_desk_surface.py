"""Permukaan Desk satu akun: rute yang ada, daftar yang boleh dibaca, picker yang tetap hidup."""

import frappe
from frappe.boot import get_bootinfo
from frappe.tests.utils import FrappeTestCase

from container_depot import desk_surface

_STAFF = "zz.desk-surface-staff@example.com"

# Data app lain yang terbaca SETIAP System User cuma karena role otomatis `All` / `Desk User`:
# daftarnya harus kosong DAN rutenya harus hilang.
_BLOCKED = ("HD Ticket", "Leave Ledger Entry", "Quality Goal")

# Layar admin Desk. Isinya tetap boleh DIBACA server (link report di workspace dibangun dari
# `frappe.get_list("Report")`), yang hilang cuma rutenya — jadi diuji terpisah.
_NO_ROUTE = _BLOCKED + ("Report", "Workspace", "Desktop Icon", "Module Def")


class TestDeskSurface(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", _STAFF):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": _STAFF,
					"first_name": "ZZ Desk Surface Staff",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			# Profil nyata Admin Ops: role-nya plus companion role standar ERPNext yang
			# COMPANION_ROLES pasangkan — itu yang memberi Item / Customer / pajak.
			from container_depot.install import COMPANION_ROLES

			user.add_roles("Admin Ops", *COMPANION_ROLES["Admin Ops"])
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.delete_doc("User", _STAFF, force=1, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = frappe._dict()

	def _as_staff(self, cmd):
		frappe.set_user(_STAFF)
		frappe.local.form_dict = frappe._dict({"cmd": cmd})

	def test_inherited_doctypes_are_blocked(self):
		for doctype in _BLOCKED:
			with self.subTest(doctype=doctype):
				self.assertTrue(desk_surface.is_blocked(doctype, _STAFF))

	def test_its_own_work_is_not_blocked(self):
		"""Doctype yang role-nya sendiri berikan, plus rakitan Desk yang dipakai form."""
		for doctype in ("Container Booking", "Container", "Item", "File", "Contact"):
			with self.subTest(doctype=doctype):
				self.assertFalse(desk_surface.is_blocked(doctype, _STAFF))

	def test_list_read_is_empty_for_a_blocked_doctype(self):
		self._as_staff("frappe.desk.reportview.get")
		self.assertEqual(frappe.get_list("HD Ticket", limit_page_length=5), [])

	def test_picker_is_not_touched(self):
		"""Master harus tetap bisa DIPILIH di form yang memang boleh dibuka."""
		self._as_staff("frappe.desk.search.search_link")
		self.assertTrue(frappe.get_list("UOM", limit_page_length=5))

	def test_boot_drops_the_routes(self):
		frappe.set_user(_STAFF)
		boot = get_bootinfo()
		before = set(boot.user.get("can_read") or [])
		desk_surface.prune_boot_can_read(bootinfo=boot)
		after = set(boot.user.get("can_read") or [])

		self.assertTrue(before & set(_NO_ROUTE), "fixture no longer inherits them")
		self.assertFalse(after & set(_NO_ROUTE))
		# Yang dipakai sehari-hari harus selamat: pekerjaannya sendiri, profilnya, lampiran.
		for doctype in ("Container Booking", "User", "File", "ToDo"):
			self.assertIn(doctype, after, doctype)

	def test_a_system_manager_keeps_everything(self):
		frappe.set_user("Administrator")
		boot = get_bootinfo()
		before = list(boot.user.get("can_read") or [])
		desk_surface.prune_boot_can_read(bootinfo=boot)
		self.assertEqual(before, list(boot.user.get("can_read") or []))
		self.assertFalse(desk_surface.is_blocked("HD Ticket", "Administrator"))
