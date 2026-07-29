"""Gate Out Plan — customer lift-on (gate-out) notice → prep priority.

Covers the whole point of the feature:
- stamping ``target_lift_on`` / ``gate_out_plan`` onto each listed Container while Open,
  and releasing it on Fulfilled / Cancelled / row-removal / delete (without clobbering a
  stamp another plan owns);
- readiness computed from the tank's open Cleaning / M&R work;
- the denormalised target pushed onto already-open orders so the worklists sort by it;
- the Email → Order bridge exposing a "Gate Out" prefill.

The controller writes to the Container via ``db.set_value`` (no commit); FrappeTestCase
rolls back, and tearDown also deletes explicitly to be safe.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.operations import cleaning
from container_depot.operations.mail_to_order import get_order_prefill
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_container

_DEPOT = "OAK1"


class TestGateOutPlan(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._principal = ensure_test_customer("GOP Test Principal")
		self._containers = []
		self._plans = []
		self._orders = []       # Cleaning Order names
		self._repairs = []      # Repair Order names
		self._comms = []

	def tearDown(self):
		for p in self._plans:
			frappe.db.delete("Gate Out Plan Item", {"parent": p})
			frappe.db.delete("Gate Out Plan", {"name": p})
		for o in self._orders:
			frappe.db.delete("Cleaning Order", {"name": o})
		for r in self._repairs:
			frappe.db.delete("Repair Order", {"name": r})
		for cm in self._comms:
			frappe.db.delete("Communication", {"name": cm})
		for c in self._containers:
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Repair Order", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno, **kw):
		kw.setdefault("principal", self._principal)
		kw.setdefault("depot", _DEPOT)
		c = _make_container(cno, **kw)
		self._containers.append(c)
		return c

	def _plan(self, rows, *, status="Open", **kw):
		"""rows = list of (container, target_date)."""
		doc = frappe.get_doc({
			"doctype": "Gate Out Plan",
			"principal": kw.pop("principal", self._principal),
			"depot": kw.pop("depot", _DEPOT),
			"source": "Email",
			"status": status,
			"containers": [{"container": c, "target_lift_on": d} for c, d in rows],
			**kw,
		}).insert(ignore_permissions=True)
		self._plans.append(doc.name)
		return doc

	def _cleaning(self, container, status="Pending"):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": status,
		}).insert(ignore_permissions=True)
		self._orders.append(co.name)
		return co.name

	def _repair(self, container, status="Draft"):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": status,
		}).insert(ignore_permissions=True)
		self._repairs.append(ro.name)
		return ro.name

	def _target(self, container):
		return frappe.db.get_value("Container", container, ["target_lift_on", "gate_out_plan"], as_dict=True)

	# --- stamping -------------------------------------------------------------
	def test_open_plan_stamps_container(self):
		c = self._container("GOPSTAMP001")
		d = add_days(today(), 5)
		plan = self._plan([(c, d)])
		got = self._target(c)
		self.assertEqual(str(got.target_lift_on), str(d))
		self.assertEqual(got.gate_out_plan, plan.name)

	def test_fulfilled_releases_stamp(self):
		c = self._container("GOPFULL0001")
		plan = self._plan([(c, add_days(today(), 5))])
		plan.status = "Fulfilled"
		plan.save(ignore_permissions=True)
		got = self._target(c)
		self.assertIsNone(got.target_lift_on)
		self.assertIsNone(got.gate_out_plan)

	def test_delete_releases_stamp(self):
		c = self._container("GOPDEL00001")
		plan = self._plan([(c, add_days(today(), 5))])
		frappe.delete_doc("Gate Out Plan", plan.name, ignore_permissions=True, force=True)
		self._plans.remove(plan.name)
		self.assertIsNone(self._target(c).target_lift_on)

	def test_dropping_a_row_releases_that_container(self):
		a = self._container("GOPDROP001A")
		b = self._container("GOPDROP001B")
		d = add_days(today(), 4)
		plan = self._plan([(a, d), (b, d)])
		self.assertEqual(str(self._target(a).target_lift_on), str(d))
		# Remove B's row, keep A.
		plan.set("containers", [r for r in plan.containers if r.container == a])
		plan.save(ignore_permissions=True)
		self.assertEqual(str(self._target(a).target_lift_on), str(d))
		self.assertIsNone(self._target(b).target_lift_on)

	def test_does_not_clobber_another_plans_stamp(self):
		c = self._container("GOPSHARE001")
		p1 = self._plan([(c, add_days(today(), 3))])
		# A second plan lists the same container (last write wins → points to p2).
		p2 = self._plan([(c, add_days(today(), 2))])
		self.assertEqual(self._target(c).gate_out_plan, p2.name)
		# Closing p1 must NOT clear the stamp that p2 now owns.
		p1.status = "Cancelled"
		p1.save(ignore_permissions=True)
		got = self._target(c)
		self.assertEqual(got.gate_out_plan, p2.name)
		self.assertIsNotNone(got.target_lift_on)

	# --- readiness ------------------------------------------------------------
	def test_readiness_ready_when_no_open_work(self):
		c = self._container("GOPRDY0001")
		plan = self._plan([(c, add_days(today(), 5))])
		row = plan.containers[0]
		self.assertEqual(row.readiness, "Siap")
		self.assertEqual(row.is_ready, 1)
		self.assertEqual(plan.readiness_summary, "1/1 siap")

	def test_readiness_flags_open_cleaning_and_mr(self):
		c = self._container("GOPRDY0002")
		self._cleaning(c)
		self._repair(c)
		plan = self._plan([(c, add_days(today(), 5))])
		row = plan.containers[0]
		self.assertEqual(row.is_ready, 0)
		self.assertIn("Cleaning", row.readiness)
		self.assertIn("M&R", row.readiness)
		self.assertEqual(plan.readiness_summary, "0/1 siap")

	def test_next_lift_on_is_earliest(self):
		a = self._container("GOPNEXT001A")
		b = self._container("GOPNEXT001B")
		plan = self._plan([(a, add_days(today(), 9)), (b, add_days(today(), 2))])
		self.assertEqual(str(plan.next_lift_on), str(add_days(today(), 2)))

	# --- denormalisation onto open orders -------------------------------------
	def test_push_target_onto_open_cleaning_order(self):
		c = self._container("GOPPUSH001")
		co = self._cleaning(c)
		d = add_days(today(), 3)
		plan = self._plan([(c, d)])
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_lift_on")), str(d))
		# Closing the plan clears the denormalised copy too.
		plan.status = "Fulfilled"
		plan.save(ignore_permissions=True)
		self.assertIsNone(frappe.db.get_value("Cleaning Order", co, "target_lift_on"))

	def test_new_order_inherits_target_via_fetch_from(self):
		c = self._container("GOPFETCH001")
		d = add_days(today(), 6)
		self._plan([(c, d)])
		# An order created AFTER the container is stamped inherits it via fetch_from.
		co = self._cleaning(c)
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_lift_on")), str(d))

	def test_worklist_sorts_nearest_target_first(self):
		near = self._container("GOPSORT00NR")
		far = self._container("GOPSORT00FR")
		co_far = self._cleaning(far)     # unstamped → should sink
		co_near = self._cleaning(near)
		self._plan([(near, add_days(today(), 1))])
		items = cleaning.list_open_cleaning_orders(page_length=0)["items"]
		names = [i["name"] for i in items]
		self.assertIn(co_near, names)
		self.assertIn(co_far, names)
		self.assertLess(names.index(co_near), names.index(co_far))

	# --- email bridge ---------------------------------------------------------
	def test_email_prefill_maps_to_gate_out_plan(self):
		comm = frappe.get_doc({
			"doctype": "Communication", "communication_type": "Communication",
			"communication_medium": "Email", "sent_or_received": "Received",
			"subject": "Lift on next week", "content": "Tolong siapkan tank kami.",
			"sender": "ops@example.com",
		}).insert(ignore_permissions=True)
		self._comms.append(comm.name)
		res = get_order_prefill(comm.name, "Gate Out")
		self.assertEqual(res["doctype"], "Gate Out Plan")
		self.assertEqual(res["values"]["reff_email"], comm.name)
		self.assertIn("notes", res["values"])
