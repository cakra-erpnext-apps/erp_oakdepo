"""Container master, 2026-10-08: what the system fills in is detail only once the tank exists.

* The three "(otomatis)" sections and Letak Tank di Yard may be typed while registering a tank;
  after it is saved only the Administrator account changes them by hand. System code
  (``ignore_permissions`` / ``in_status_automation``) is never refused.
* The Riwayat Order tab lists every order raised for the tank, newest first, voided ones too.

Fixtures are deleted in tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot.doctype.container.container import order_history
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_work_claim import _user

PREFIX = "MLCK"
OPS = "mlck-ops@example.com"


class TestContainerMasterLock(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_user(OPS, "Admin Ops")
		self.principal = ensure_test_customer("Master Lock Principal")

	def tearDown(self):
		frappe.set_user("Administrator")
		like = ["like", f"{PREFIX}%"]
		for dt in ("Cleaning Order", "Repair Order", "Inspection", "Container Activity", "Container Movement", "Storage Charge"):
			frappe.db.delete(dt, {"container": like})
		frappe.db.delete("Container", {"name": like})
		if frappe.db.exists("User", OPS):
			frappe.delete_doc("User", OPS, ignore_permissions=True, force=True)
		frappe.db.commit()

	def _new(self, no, **kw):
		return frappe.get_doc({
			"doctype": "Container", "container_no": f"{PREFIX}{no}", "container_type": "ISO Tank",
			"principal": self.principal, **kw,
		})

	def test_typed_while_registering_locked_once_saved(self):
		frappe.set_user(OPS)
		doc = self._new("0000001", ex_vessel="MV REG", yard_zone="A")
		doc.insert()  # registering: the otomatis fields are still an isian
		self.assertEqual(frappe.db.get_value("Container", doc.name, "ex_vessel"), "MV REG")

		for field, value in (("ex_vessel", "MV LAIN"), ("in_date", today()), ("yard_zone", "B")):
			doc.reload()
			doc.set(field, value)
			with self.assertRaises(frappe.PermissionError, msg=field):
				doc.save()

		# What is not system-filled stays editable.
		doc.reload()
		doc.serial_no = "SN-1"
		doc.save()

	def test_the_administrator_and_the_system_may_still_change_them(self):
		doc = self._new("0000002").insert(ignore_permissions=True)
		doc.ex_vessel = "MV ADMIN"
		doc.save()  # as Administrator
		frappe.set_user(OPS)
		doc.reload()
		doc.ex_vessel = "MV SYSTEM"
		doc.save(ignore_permissions=True)  # system code
		self.assertEqual(frappe.db.get_value("Container", doc.name, "ex_vessel"), "MV SYSTEM")

	def test_order_history_lists_every_order_newest_first(self):
		tank = self._new("0000003").insert(ignore_permissions=True).name
		old = frappe.get_doc({
			"doctype": "Cleaning Order", "container": tank, "status": "Service Setup",
			"plan_date": add_days(today(), -5), "reff_doc": "REF-OLD",
		}).insert(ignore_permissions=True)
		new = frappe.get_doc({
			"doctype": "Repair Order", "container": tank, "plan_date": today(), "job_type": "Periodic Test",
		}).insert(ignore_permissions=True)
		frappe.db.set_value("Cleaning Order", old.name, {"docstatus": 2, "status": "Cancelled"})

		rows = order_history(tank)
		self.assertEqual([r["name"] for r in rows], [new.name, old.name])
		self.assertEqual(rows[0]["kind"], "Periodic Test")
		self.assertEqual((rows[1]["reff_doc"], rows[1]["cancelled"]), ("REF-OLD", True))
