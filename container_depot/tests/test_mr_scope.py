"""M&R vs Periodic Test: satu doctype (Repair Order), dua menu, dua tim.

Dijalankan sebagai user sungguhan (bukan Administrator, yang melewati semua izin):
Team Repair hanya melihat M&R, Team Periodic hanya Periodic Test, SPV Lapangan keduanya —
di menu PWA, di list, di dokumen tunggal, di endpoint, dan di bel notifikasi.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.mr_scope import PERIODIC, REPAIR
from container_depot.ess.context import allowed_menu
from container_depot.tests.test_eir import _make_container

USERS = {
	"Team Repair": "mrs-repair@example.com",
	"Team Periodic": "mrs-periodic@example.com",
	"SPV Lapangan": "mrs-spv@example.com",
}


def _user(email, role):
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, ignore_permissions=True, force=True)
	frappe.get_doc({
		"doctype": "User", "email": email, "first_name": email.split("@")[0],
		"send_welcome_email": 0, "user_type": "System User",
	}).insert(ignore_permissions=True).add_roles(role)


class TestMrScope(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for role, email in USERS.items():
			_user(email, role)
		cls.container = _make_container("MRSU1000001")
		cls.orders = {}
		for job_type in (REPAIR, PERIODIC):
			cls.orders[job_type] = frappe.get_doc({
				"doctype": "Repair Order", "container": cls.container,
				"job_type": job_type, "status": "Pending",
			}).insert(ignore_permissions=True).name
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		names = list(cls.orders.values())
		frappe.db.delete("Notification Log", {"document_type": "Repair Order", "document_name": ["in", names]})
		frappe.db.delete("Repair Order", {"container": cls.container})
		frappe.db.delete("Container Activity", {"container": cls.container})
		frappe.db.delete("Comment", {"reference_doctype": "Container", "reference_name": cls.container})
		frappe.db.delete("Container", {"name": cls.container})
		for email in USERS.values():
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _as(self, role):
		frappe.set_user(USERS[role])
		frappe.local._mr_scope_readers = None

	def test_periodic_order_gets_its_own_number(self):
		self.assertTrue(self.orders[PERIODIC].startswith("PT-"))
		self.assertTrue(self.orders[REPAIR].startswith("RO-"))
		self.assertTrue(frappe.db.get_value("Repair Order", self.orders[PERIODIC], "repair_order_id").startswith("PT-"))

	def test_menu_split(self):
		self._as("Team Repair")
		menu = set(allowed_menu())
		self.assertIn("mr", menu)
		self.assertNotIn("periodic", menu)

		self._as("Team Periodic")
		menu = set(allowed_menu())
		self.assertIn("periodic", menu)
		self.assertNotIn("mr", menu)

		self._as("SPV Lapangan")
		self.assertTrue({"mr", "periodic"} <= set(allowed_menu()))

	def test_list_and_document_split(self):
		for role, own, other in (("Team Repair", REPAIR, PERIODIC), ("Team Periodic", PERIODIC, REPAIR)):
			with self.subTest(role=role):
				self._as(role)
				seen = set(frappe.get_list("Repair Order", filters={"container": self.container}, pluck="name"))
				self.assertEqual(seen, {self.orders[own]})
				self.assertTrue(frappe.has_permission("Repair Order", "write", doc=self.orders[own]))
				self.assertFalse(frappe.has_permission("Repair Order", "read", doc=self.orders[other]))

		self._as("SPV Lapangan")
		seen = set(frappe.get_list("Repair Order", filters={"container": self.container}, pluck="name"))
		self.assertEqual(seen, set(self.orders.values()))

	def test_endpoints_refuse_the_other_menu(self):
		from container_depot.ess import repairs

		self._as("Team Periodic")
		with self.assertRaises(frappe.PermissionError):
			repairs.mr_execution(job_type=REPAIR)
		with self.assertRaises(frappe.PermissionError):
			repairs.mr_order_detail(repair_order=self.orders[REPAIR])
		names = {r["name"] for r in repairs.mr_execution(job_type=PERIODIC)["items"]}
		self.assertIn(self.orders[PERIODIC], names)
		self.assertNotIn(self.orders[REPAIR], names)

	def test_bell_reaches_only_the_owning_team(self):
		from container_depot.container_depot.notify import notify_repair_forwarded_to_team

		frappe.set_user("Administrator")
		notify_repair_forwarded_to_team(self.orders[PERIODIC])
		got = set(frappe.get_all(
			"Notification Log",
			filters={"document_name": self.orders[PERIODIC], "for_user": ["in", list(USERS.values())]},
			pluck="for_user",
		))
		self.assertIn(USERS["Team Periodic"], got)
		self.assertNotIn(USERS["Team Repair"], got)
		self.assertIn(USERS["SPV Lapangan"], got)
		subject = frappe.db.get_value(
			"Notification Log", {"document_name": self.orders[PERIODIC], "for_user": USERS["Team Periodic"]}, "subject"
		)
		self.assertTrue(subject.startswith("Periodic Test"))

	def test_notification_route_follows_the_job_type(self):
		from container_depot.ess.notification_routes import route_for

		self.assertEqual(route_for("Repair Order", self.orders[PERIODIC], "repair_order_forwarded"),
			f"/periodic?o={self.orders[PERIODIC]}")
		self.assertEqual(route_for("Repair Order", self.orders[REPAIR], "repair_order_forwarded"),
			f"/mr?o={self.orders[REPAIR]}")
