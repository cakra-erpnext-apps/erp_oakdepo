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

from container_depot.container_depot import periodic
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

	# --- gate-out gate (same as Cleaning / M&R) --------------------------------
	def test_open_order_blocks_gate_out_until_finished(self):
		"""An unfinished Periodic Test Order keeps the tank In_Depot (not Available), so a
		Tank Out booking / gate-out is blocked until the test is done."""
		c = self._container("PTO0011")
		frappe.db.set_value("Container", c, "status", "Available")
		# opening a periodic test = unfinished work -> tank drops to In_Depot
		doc = self._order(c, test_type="2,5Y", periodic_date=today())
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")
		# finishing it releases the tank back to Available
		self._advance(doc, "Approved", "In Progress", "Completed")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")

	# --- billing (identical to M&R) -------------------------------------------
	def _completed_order(self, cno, used):
		doc = self._order(self._container(cno), test_type="2,5Y", periodic_date=today(), used=used)
		self._advance(doc, "Approved", "In Progress", "Completed")
		doc.reload()
		return doc

	def _sweep(self):
		from container_depot.consolidated_billing import _periodic_lines

		return _periodic_lines(self._principal, "2000-01-01 00:00:00", f"{today()} 23:59:59")

	def test_completed_order_is_swept_item_by_item(self):
		"""One invoice line PER USED ITEM, each carrying its item_code — the same rule as
		M&R, and the only way the invoice can look up each item's contract manhour. A lump
		"Periodic Test PTO-xxx" line would book zero hours."""
		doc = self._completed_order(
			"PTOBILL0001",
			[{"item": "Lift Off", "quantity": 2}, {"item": "Lift On", "quantity": 1}],
		)
		lines = [ln for u in self._sweep() for ln in u["lines"]]
		self.assertEqual({ln["item_code"] for ln in lines}, {"Lift Off", "Lift On"})
		self.assertTrue(all(ln.get("item_code") for ln in lines), "every line must carry item_code")
		self.assertTrue(all(ln["description"].startswith("Periodic Test ") for ln in lines))
		self.assertEqual([u["sources"][0]["dt"] for u in self._sweep()], ["Periodic Test Order"])
		self.assertEqual(self._sweep()[0]["sources"][0]["name"], doc.name)

	def test_rejected_lines_are_not_billed(self):
		"""Same rule the order's own total uses — an owner-rejected line is not charged."""
		self._completed_order(
			"PTOBILL0002",
			[
				{"item": "Lift Off", "quantity": 1, "decision": "Rejected"},
				{"item": "Lift On", "quantity": 1},
			],
		)
		lines = [ln for u in self._sweep() for ln in u["lines"]]
		self.assertEqual({ln["item_code"] for ln in lines}, {"Lift On"})

	def test_an_already_billed_order_is_not_swept_again(self):
		from container_depot.consolidated_billing import _mark_billed, _unmark_billed

		doc = self._completed_order("PTOBILL0003", [{"item": "Lift Off", "quantity": 1}])
		self.assertTrue(self._sweep(), "unbilled work must be swept")

		_mark_billed("Periodic Test Order", doc.name, "SOME-SI")
		doc.reload()
		self.assertEqual(doc.billing_status, "Client Billed")
		self.assertEqual(doc.sales_invoice, "SOME-SI")
		self.assertEqual(self._sweep(), [], "a billed order must never be swept twice")

		# Rollback puts it back in the queue, exactly as it does for M&R.
		_unmark_billed("Periodic Test Order", doc.name)
		doc.reload()
		self.assertEqual(doc.billing_status, "Unbilled")
		self.assertIsNone(doc.sales_invoice)
		self.assertTrue(self._sweep())

	def test_report_lists_it_under_its_own_order_type(self):
		"""The billing treatment is shared with M&R; the Order Type filter is what tells
		them apart."""
		from container_depot.container_depot.report.order_billing_status.order_billing_status import (
			ORDER_TYPES,
			execute,
		)

		doc = self._completed_order("PTOBILL0004", [{"item": "Lift Off", "quantity": 1}])
		self.assertIn("Periodic Test Order", ORDER_TYPES)
		_, rows = execute({"customer": self._principal, "order_type": "Periodic Test Order"})
		mine = [r for r in rows if r["order"] == doc.name]
		self.assertEqual(len(mine), 1)
		self.assertEqual(mine[0]["order_type"], "Periodic Test Order")
		self.assertEqual(mine[0]["invoice_status"], "Not Invoiced")
