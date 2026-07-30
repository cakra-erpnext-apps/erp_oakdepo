"""Periodic Test Order — the M&R-style periodic-test work/billing flow.

Covers: principal auto-fetch, due-date computed from test_type, per-currency totals with
rejected lines excluded, the owner-approval status machine (illegal transitions blocked),
completion pushing next_pt_due / last_test_date onto the Container master (the single source
of truth), and the Admin-Ops reopen-to-Draft rewind.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, getdate, today

from container_depot.operations import periodic
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_container

_DEPOT = "OAK1"


def _due(months):
	return str(getdate(add_to_date(getdate(today()), months=months)))


class TestPeriodicTestOrder(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._principal = ensure_test_customer("PTO Test Principal")
		self._containers = []
		self._orders = []

	def tearDown(self):
		for o in self._orders:
			frappe.db.delete("Periodic Used Item", {"parent": o})
			frappe.db.delete("Periodic Cost Total", {"parent": o})
			frappe.db.delete("Periodic Test Order", {"name": o})
		for c in self._containers:
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Periodic Test Order", {"container": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno, **kw):
		kw.setdefault("principal", self._principal)
		kw.setdefault("depot", _DEPOT)
		c = _make_container(cno, **kw)
		self._containers.append(c)
		return c

	def _order(self, container, *, test_type="2,5Y", periodic_date=None, used=None, status="Draft"):
		doc = frappe.get_doc({
			"doctype": "Periodic Test Order",
			"container": container,
			"test_type": test_type,
			"periodic_date": periodic_date,
			"status": status,
			"used_items": used or [],
		}).insert(ignore_permissions=True)
		self._orders.append(doc.name)
		return doc

	def _advance(self, doc, *statuses):
		for s in statuses:
			doc.status = s
			doc.save(ignore_permissions=True)
		return doc

	# --- basics ---------------------------------------------------------------
	def test_principal_fetched_and_order_created_stamped(self):
		doc = self._order(self._container("PTO0001"))
		self.assertEqual(doc.principal, self._principal)
		self.assertEqual(doc.billed_to, self._principal)
		self.assertIsNotNone(doc.order_created)

	def test_due_date_computed_by_type(self):
		d1 = self._order(self._container("PTO0002A"), test_type="2,5Y", periodic_date=today())
		self.assertEqual(str(d1.due_date), _due(30))
		d2 = self._order(self._container("PTO0002B"), test_type="5Y", periodic_date=today())
		self.assertEqual(str(d2.due_date), _due(60))

	def test_totals_grouped_and_rejected_excluded(self):
		doc = self._order(self._container("PTO0003"), used=[
			{"line_type": "Jasa", "item_rate": 100, "quantity": 1},
			{"line_type": "Jasa", "item_rate": 50, "quantity": 2, "decision": "Rejected"},
		])
		self.assertEqual(doc.total_cost, 100)  # rejected 2x50 excluded
		self.assertEqual(len(doc.totals), 1)
		self.assertEqual(doc.totals[0].total, 100)

	# --- status machine -------------------------------------------------------
	def test_illegal_transition_blocked(self):
		doc = self._order(self._container("PTO0004"))
		doc.status = "In Progress"  # Draft -> In Progress skips approval
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_complete_pushes_due_to_container(self):
		c = self._container("PTO0005")
		doc = self._order(c, test_type="2,5Y", periodic_date=today())
		self._advance(doc, "Approved", "In Progress", "Completed")  # bypass path
		self.assertEqual(doc.status, "Completed")
		cv = frappe.db.get_value("Container", c, ["next_pt_due", "last_test_date"], as_dict=True)
		self.assertEqual(str(cv.next_pt_due), _due(30))
		self.assertEqual(str(cv.last_test_date), str(getdate(today())))
		self.assertTrue(
			frappe.db.exists("Container Activity", {"container": c, "activity_type": "Periodic Test"})
		)

	def test_reopen_to_draft_rewinds(self):
		doc = self._order(
			self._container("PTO0006"),
			used=[{"line_type": "Jasa", "item_rate": 100, "quantity": 1, "decision": "Approved"}],
		)
		self._advance(doc, "Service Setup", "Pending Approval", "Approved")
		periodic.reopen_to_draft(doc.name)
		doc.reload()
		self.assertEqual(doc.status, "Draft")
		self.assertEqual(doc.used_items[0].decision, "Pending")

	# --- PWA execution console -------------------------------------------------
	def test_execution_worklist_shows_only_approved_and_in_progress(self):
		draft = self._order(self._container("PTO0007A"))
		appr = self._advance(self._order(self._container("PTO0007B")), "Approved")
		names = {r["name"] for r in periodic.list_pt_execution()["items"]}
		self.assertIn(appr.name, names)
		self.assertNotIn(draft.name, names)  # Draft is not execution-ready

	def test_start_test_moves_approved_to_in_progress(self):
		doc = self._advance(self._order(self._container("PTO0008")), "Approved")
		periodic.start_test(doc.name)
		doc.reload()
		self.assertEqual(doc.status, "In Progress")
		self.assertIsNotNone(doc.start_date)
		# only Approved may start
		with self.assertRaises(frappe.ValidationError):
			periodic.start_test(doc.name)

	def test_save_pt_order_completes_and_defaults_periodic_date(self):
		c = self._container("PTO0009")
		doc = self._advance(self._order(c, test_type="5Y"), "Approved", "In Progress")
		res = periodic.save_pt_order(periodic_test_order=doc.name, submit=1)
		self.assertEqual(res["status"], "Completed")
		doc.reload()
		# periodic_date defaulted to today -> due_date computed (5Y = 60 months) -> pushed to Container
		self.assertEqual(str(doc.periodic_date), str(getdate(today())))
		cv = frappe.db.get_value("Container", c, ["next_pt_due", "last_test_date"], as_dict=True)
		self.assertEqual(str(cv.next_pt_due), _due(60))
		self.assertEqual(str(cv.last_test_date), str(getdate(today())))

	def test_history_lists_completed(self):
		doc = self._advance(
			self._order(self._container("PTO0010")), "Approved", "In Progress"
		)
		periodic.save_pt_order(periodic_test_order=doc.name, submit=1)
		names = {r["name"] for r in periodic.list_pt_history()["items"]}
		self.assertIn(doc.name, names)
