"""M&R (Maintenance & Repair) flow (container_depot.mr): an EIR with damage auto-creates an
editable Draft Repair Order; the estimate goes to the owner, and the approved parts leave
the warehouse (a Material Issue Stock Entry) the moment the money is agreed — not when the
work is reported done. The team then works the job and Desk signs it off, which returns the
tank to the ready pool.

WHERE THE STOCK MOVES, AND WHY IT MOVES THERE
---------------------------------------------
Completion used to issue the parts. That reads tidily and is wrong in the yard: the
workshop cannot repair anything with parts still on a shelf, so by the time anyone presses
"selesai" the parts left days ago and the ledger has been lying ever since. Both roads to
Approved — the owner's own yes and the Admin-Ops bypass — issue instead, because from the
warehouse's point of view they are one event: someone with authority said these parts are
being used. Completion is now the sign-off on the WORK.

That moves the burden to the rewind: an order that took its parts and then goes back to
Draft / Cancelled / Rejected must give them back, which the controller does by cancelling
the Material Issue. Those tests live here too.

Stock movements + Repair Order saves commit, so created docs (incl. the seeded Material
Receipt and the issued Stock Entry) are cancelled/removed explicitly after each test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import cint, flt

from container_depot.container_depot import eir, eir_followups, mr
from container_depot.tests.test_eir import _make_container

_ITEM = "MR-TEST-SEALKIT"
_SERVICE = "MR-TEST-LABOR"
_WH_NAME = "MR Test Store"


class TestMaintenanceRepairFlow(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._orders = []
		self._inspections = []
		self._stock_entries = []
		self.company = mr._resolve_company()
		# Decouple the stock test from ERPNext's backdated-receipt posting-order quirk
		# inside the test transaction: allow negative stock so the issue always posts
		# (the Bin total — what we assert — is still correct: 10 received - 3 issued = 7).
		self._neg_stock = frappe.db.get_single_value("Stock Settings", "allow_negative_stock")
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)

	def _safe(self, fn):
		"""Run a cleanup step without letting its failure abort the rest of tearDown."""
		try:
			fn()
		except Exception:
			frappe.db.rollback()

	def tearDown(self):
		# Cancel + drop EVERY stock entry that touched the test item (tracked or not —
		# an errored test may have submitted an issue without recording its name), so the
		# test leaves no stock ledger behind. Each step is isolated so one failure can't
		# strand the others (which would poison the next run with leftover containers).
		touched = frappe.get_all("Stock Entry Detail", filters={"item_code": _ITEM}, pluck="parent", distinct=True)
		for se in set(self._stock_entries) | set(touched):
			self._safe(lambda se=se: self._drop_stock_entry(se))
		for o in self._orders:
			self._safe(lambda o=o: frappe.db.delete("Repair Order", {"name": o}))
		for c in self._containers:
			self._safe(lambda c=c: frappe.db.delete("Repair Order", {"container": c}))
			self._safe(lambda c=c: frappe.db.delete("Container Activity", {"container": c}))
			self._safe(lambda c=c: frappe.db.delete("Container", {"name": c}))
		for ins in self._inspections:
			self._safe(lambda ins=ins: frappe.db.delete("Inspection", {"name": ins}))
		self._safe(lambda: frappe.db.delete("Bin", {"item_code": _ITEM}))
		for dt, name in (("Item", _ITEM), ("Item", _SERVICE), ("Warehouse", self._wh_name())):
			if name:
				self._safe(lambda dt=dt, name=name: frappe.db.exists(dt, name) and frappe.delete_doc(dt, name, force=True, ignore_permissions=True))
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", self._neg_stock or 0)
		frappe.db.commit()
		super().tearDown()

	def _drop_stock_entry(self, se):
		if not frappe.db.exists("Stock Entry", se):
			return
		doc = frappe.get_doc("Stock Entry", se)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Stock Entry", se, force=True, ignore_permissions=True)

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno, **kw):
		c = _make_container(cno, **kw)
		self._containers.append(c)
		return c

	def _wh_name(self):
		return frappe.db.get_value("Warehouse", {"warehouse_name": _WH_NAME, "company": self.company}, "name")

	def _ensure_warehouse(self):
		existing = self._wh_name()
		if existing:
			return existing
		wh = frappe.get_doc({
			"doctype": "Warehouse", "warehouse_name": _WH_NAME, "company": self.company, "is_group": 0,
		}).insert(ignore_permissions=True)
		return wh.name

	def _ensure_item(self):
		if not frappe.db.exists("Item", _ITEM):
			frappe.get_doc({
				"doctype": "Item", "item_code": _ITEM, "item_name": "M&R Test Seal Kit",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
				"stock_uom": "Nos", "is_stock_item": 1,
			}).insert(ignore_permissions=True)
		return _ITEM

	def _receive_stock(self, warehouse, qty):
		"""Seed on-hand stock via a submitted Material Receipt, backdated a day so the
		later Material Issue can never race it in the stock ledger."""
		se = frappe.get_doc({
			"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": self.company,
			"to_warehouse": warehouse, "set_posting_time": 1,
			"posting_date": frappe.utils.add_days(frappe.utils.today(), -1), "posting_time": "00:00:00",
			"items": [{"item_code": _ITEM, "qty": qty, "t_warehouse": warehouse, "basic_rate": 1000}],
		})
		se.insert(ignore_permissions=True)
		se.submit()
		self._stock_entries.append(se.name)
		return se.name

	def _ensure_service_item(self):
		"""A non-stock service item — used to test completion that issues no stock."""
		if not frappe.db.exists("Item", _SERVICE):
			frappe.get_doc({
				"doctype": "Item", "item_code": _SERVICE, "item_name": "M&R Test Labor",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
				"stock_uom": "Nos", "is_stock_item": 0, "is_sales_item": 1,
			}).insert(ignore_permissions=True)
		return _SERVICE

	def _to_in_progress(self, ro, used_items, warehouse=None):
		"""Drive a Draft M&R into In Progress the way the depot does: save the estimate ->
		publish to the owner -> owner Approves (the parts leave stock here) -> Admin Ops
		forwards it to the team -> the team starts.

		``forward_to_team`` is a separate press on purpose: the owner's yes says the money is
		agreed, not that the depot is ready to start. Until it is pressed the job is not on
		the PWA worklist at all, so a helper that skipped it would test a path no operator
		can walk.

		There is no order-level source warehouse any more, so ``warehouse`` is stamped onto
		every row that does not name its own (the controller clears it again on services)."""
		if warehouse:
			used_items = [{**u, "warehouse": u.get("warehouse") or warehouse} for u in used_items]
		mr.save_mr_order(repair_order=ro, used_items=used_items, submit=False)
		mr.publish_to_owner(ro)
		mr.record_decision(ro, "Approved")
		mr.forward_to_team(ro)
		mr.start_repair(ro)

	def _eir_with_damage(self, cno):
		c = self._container(cno)
		res = eir.create_eir(
			inspection_type="EIR-In", container=c,
			lines=[{"item_code": "11", "damage_code": "12", "remarks": "valve broken"}], submit=True,
		)
		self._inspections.append(res["name"])
		return c, res["name"]

	# --- auto-create from EIR -------------------------------------------------
	def test_eir_damage_creates_draft_mr(self):
		c, eir_name = self._eir_with_damage("MRDMG000001")
		ro = frappe.db.get_value(
			"Repair Order", {"container": c}, ["name", "status", "inspection"], as_dict=True
		)
		self.assertTrue(ro)
		self._orders.append(ro.name)
		self.assertEqual(ro.status, "Draft")
		self.assertEqual(ro.inspection, eir_name)

	def test_detail_copies_eir_damages(self):
		c, _ = self._eir_with_damage("MRDMG000002")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		d = mr.get_mr_order_detail(ro)
		self.assertEqual(d["container"], c)
		self.assertEqual(d["status"], "Draft")
		# Section 1: the EIR damage entry was copied into the read-only Damages snapshot.
		self.assertGreaterEqual(len(d["damages"]), 1)
		self.assertEqual(d["damages"][0]["damage_code"], "12")
		# Section 2 starts empty — the team adds the services/parts (each with its gudang).
		self.assertEqual(d["used_items"], [])

	# --- lifecycle ------------------------------------------------------------
	def test_start_marks_in_progress(self):
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRSTART0001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		# Approval is mandatory: the estimate must be submitted and approved before start.
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "In Progress")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")

	def test_start_requires_approval(self):
		"""start_repair is rejected on a Draft M&R — approval is mandatory."""
		c, _ = self._eir_with_damage("MRGATE00001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		with self.assertRaises(frappe.ValidationError):
			mr.start_repair(ro)

	def test_start_requires_the_hand_over_to_the_team(self):
		"""Approved is not the starting gun — Admin Ops still has to hand the job over."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRFWD000001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.save_mr_order(repair_order=ro, used_items=[{"item": _SERVICE, "quantity": 1}], submit=False)
		mr.publish_to_owner(ro)
		mr.record_decision(ro, "Approved")
		with self.assertRaises(frappe.ValidationError):
			mr.start_repair(ro)

		mr.forward_to_team(ro)
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "Pending")
		mr.start_repair(ro)
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "In Progress")

	def test_parts_leave_stock_at_approval(self):
		"""The stock moves when the money is agreed, not when the work is reported done."""
		warehouse = self._ensure_warehouse()
		self._ensure_item()
		self._receive_stock(warehouse, 10)

		c, _ = self._eir_with_damage("MRSTOCK0001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.save_mr_order(
			repair_order=ro,
			used_items=[{
				"item": _ITEM, "quantity": 3, "warehouse": warehouse,
				"remark": "Foot valve", "photos": ["/files/x.jpg"],
			}],
			submit=False,
		)
		mr.publish_to_owner(ro)
		# Still on the shelf while the owner is only being asked.
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 10.0)
		self.assertIsNone(frappe.db.get_value("Repair Order", ro, "stock_entry"))

		mr.record_decision(ro, "Approved")
		se_name = frappe.db.get_value("Repair Order", ro, "stock_entry")
		self.assertTrue(se_name)
		self._stock_entries.append(se_name)
		# 10 received - 3 issued = 7 on hand, the moment the owner said yes.
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 7.0)
		se = frappe.get_doc("Stock Entry", se_name)
		self.assertEqual(se.stock_entry_type, "Material Issue")
		self.assertEqual(flt(se.items[0].qty), 3.0)

	def test_completion_signs_off_the_work_and_frees_the_tank(self):
		"""Team submit -> Pending Review -> Desk finalises. Nothing moves in the warehouse
		across any of it: the parts went out back at approval."""
		warehouse = self._ensure_warehouse()
		self._ensure_item()
		self._receive_stock(warehouse, 10)

		c, _ = self._eir_with_damage("MRDONE00001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _ITEM, "quantity": 3}], warehouse=warehouse)
		se_name = frappe.db.get_value("Repair Order", ro, "stock_entry")
		self._stock_entries.append(se_name)
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 7.0)

		# The team reports the job done — it goes to Desk for review, NOT straight to done.
		res = mr.save_mr_order(repair_order=ro, submit=True)
		self.assertEqual(res["status"], "Pending Review")
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 7.0)
		# The tank is still held: nobody has checked the work yet.
		self.assertNotEqual(frappe.db.get_value("Container", c, "status"), "Available")

		res = mr.finalize_repair(ro)
		self.assertEqual(res["status"], "Completed")
		self.assertEqual(res["stock_entry"], se_name)  # the same issue, not a second one
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 7.0)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")

	def test_team_can_pull_a_finished_job_back_for_a_fix(self):
		"""Pending Review -> In Progress, the team's own correction before Desk signs off."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRWDRW00001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		mr.save_mr_order(repair_order=ro, submit=True)
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "Pending Review")

		mr.withdraw_review(ro)
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "In Progress")
		# Finalising is refused until it is handed back in.
		with self.assertRaises(frappe.ValidationError):
			mr.finalize_repair(ro)
		mr.save_mr_order(repair_order=ro, submit=True)
		mr.finalize_repair(ro)
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "Completed")

	def test_desk_can_close_an_approved_order_without_dispatching_it(self):
		"""The short road out of Approved: work that is already done never goes to the team.

		Plenty of M&R is a five-minute fix the Desk operator watched happen, or a
		subcontractor's job. Routing that through the PWA would mean handing it over, having
		someone open it, start it and finish it — four presses to record something that is
		over."""
		warehouse = self._ensure_warehouse()
		self._ensure_item()
		self._receive_stock(warehouse, 10)

		c, _ = self._eir_with_damage("MRDIRECT001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.save_mr_order(
			repair_order=ro,
			used_items=[{"item": _ITEM, "quantity": 2, "warehouse": warehouse}],
			submit=False,
		)
		mr.publish_to_owner(ro)
		mr.record_decision(ro, "Approved")
		se_name = frappe.db.get_value("Repair Order", ro, "stock_entry")
		self._stock_entries.append(se_name)
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 8.0)

		res = mr.finalize_repair(ro)
		self.assertEqual(res["status"], "Completed")
		# Same order, same issue — the short road skips the dispatch, not the stock.
		self.assertEqual(res["stock_entry"], se_name)
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 8.0)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")
		# A completion with no beginning reads as broken history, so start_date is stamped.
		doc = frappe.get_doc("Repair Order", ro)
		self.assertIsNotNone(doc.start_date)
		self.assertIsNotNone(doc.completion_date)

	def test_closing_is_refused_from_the_statuses_in_between(self):
		"""Only the two ends are closable: Approved (never dispatched) and Pending Review
		(the team reported it done). Pending and In Progress are somebody's open job — closing
		one under them would erase work in progress with no record of it."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRSHUT00001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.save_mr_order(repair_order=ro, used_items=[{"item": _SERVICE, "quantity": 1}], submit=False)
		mr.publish_to_owner(ro)
		with self.assertRaises(frappe.ValidationError):
			mr.finalize_repair(ro)  # Pending Approval

		mr.record_decision(ro, "Approved")
		mr.forward_to_team(ro)
		with self.assertRaises(frappe.ValidationError):
			mr.finalize_repair(ro)  # Pending — handed over, not yet picked up

		mr.start_repair(ro)
		with self.assertRaises(frappe.ValidationError):
			mr.finalize_repair(ro)  # In Progress

	def test_review_queue_holds_only_what_is_waiting_on_desk(self):
		"""The PWA "Diajukan Review" list. It is separate from the worklist on purpose: work
		waiting on somebody ELSE must not sit among work waiting on YOU."""
		self._ensure_service_item()
		names = {}
		for key, cno in (("progress", "MRRVW000001"), ("review", "MRRVW000002")):
			c, _ = self._eir_with_damage(cno)
			ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
			self._orders.append(ro)
			names[key] = ro
			self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		mr.save_mr_order(repair_order=names["review"], submit=True)

		queued = {i["name"] for i in mr.list_review_mr_orders(page_length=500)["items"]}
		self.assertIn(names["review"], queued)
		self.assertNotIn(names["progress"], queued)
		# ...and it has left the team's worklist, which is the other half of the same rule.
		working = {i["name"] for i in mr.list_mr_execution(page_length=500)["items"]}
		self.assertIn(names["progress"], working)
		self.assertNotIn(names["review"], working)
		# The row carries how big the job is — a rejected line is not work, so it is not counted.
		row = next(i for i in mr.list_review_mr_orders(page_length=500)["items"] if i["name"] == names["review"])
		self.assertEqual(row["item_count"], 1)

	def test_complete_without_parts_moves_no_stock(self):
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRNOPART001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		# A non-stock service item: approved + completed, and nothing is ever issued.
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		self.assertIsNone(frappe.db.get_value("Repair Order", ro, "stock_entry"))
		mr.save_mr_order(repair_order=ro, submit=True)
		res = mr.finalize_repair(ro)
		self.assertEqual(res["status"], "Completed")
		self.assertIsNone(res["stock_entry"])
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")

	# --- reopening a closed order ("Ajukan Revisi") ---------------------------
	def _completed(self, cno):
		"""A closed, unbilled M&R carrying one service line."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage(cno)
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		mr.save_mr_order(repair_order=ro, submit=True)
		mr.finalize_repair(ro)
		return c, ro

	def test_the_team_asks_rather_than_reopens(self):
		"""A closed M&R is Desk's record. The team can no longer pull it back the way they can
		while it is theirs (withdraw_review), so they raise a REQUEST — which moves nothing."""
		_, ro = self._completed("MRREV000001")
		res = mr.request_revision(ro, reason="las belum rapi")
		self.assertTrue(res["success"])
		doc = frappe.get_doc("Repair Order", ro)
		self.assertEqual(doc.status, "Completed")  # asking changes nothing
		self.assertEqual(cint(doc.reopen_requested), 1)
		self.assertIn("las belum rapi", doc.reopen_note)
		# The reason reaches the Desk on the order itself, not only in a bell notification.
		self.assertEqual(mr.get_mr_order_detail(ro)["reopen_note"], doc.reopen_note)

	def test_asking_is_only_for_a_closed_order(self):
		"""While the job is still theirs the team pulls it back themselves — offering both
		would make the free route look like the one that needs permission."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRREV000002")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		with self.assertRaises(frappe.ValidationError):
			mr.request_revision(ro)  # In Progress
		mr.save_mr_order(repair_order=ro, submit=True)
		with self.assertRaises(frappe.ValidationError):
			mr.request_revision(ro)  # Pending Review

	def test_admin_ops_reopens_to_in_progress_keeping_the_agreed_estimate(self):
		"""What was wrong is the repair, not the price. The owner's approval, the lines and
		the parts already issued all stand — rewinding to Draft would make the team re-quote
		work that was quoted correctly."""
		warehouse = self._ensure_warehouse()
		self._ensure_item()
		self._receive_stock(warehouse, 10)
		c, _ = self._eir_with_damage("MRREV000003")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _ITEM, "quantity": 2}], warehouse=warehouse)
		se_name = frappe.db.get_value("Repair Order", ro, "stock_entry")
		self._stock_entries.append(se_name)
		mr.save_mr_order(repair_order=ro, submit=True)
		mr.finalize_repair(ro)
		mr.request_revision(ro, reason="bocor lagi")

		mr.reopen_completed(ro, note="cek ulang")
		doc = frappe.get_doc("Repair Order", ro)
		self.assertEqual(doc.status, "In Progress")
		# The completion never happened — left standing it prints as a job that finished
		# before it was worked.
		self.assertIsNone(doc.completion_date)
		# The request has been actioned, so the badge comes off.
		self.assertEqual(cint(doc.reopen_requested), 0)
		self.assertIsNone(doc.reopen_note)
		# Estimate, approval and stock all untouched: same issue, same on-hand.
		self.assertEqual(doc.stock_entry, se_name)
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 8.0)
		self.assertTrue(all(r.decision == "Approved" for r in doc.used_items))
		# ...and it closes again the ordinary way, with no second stock movement.
		mr.save_mr_order(repair_order=ro, submit=True)
		mr.finalize_repair(ro)
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 8.0)

	def test_closing_again_clears_a_standing_request(self):
		"""The request asked for exactly this round of work. Left set, the badge follows the
		order into history and reads as an open question nobody answered."""
		_, ro = self._completed("MRREV000004")
		mr.request_revision(ro)
		mr.reopen_completed(ro)
		mr.save_mr_order(repair_order=ro, submit=True)
		mr.finalize_repair(ro)
		self.assertEqual(cint(frappe.db.get_value("Repair Order", ro, "reopen_requested")), 0)

	def test_a_billed_order_is_not_reopenable_from_here(self):
		"""Un-finishing a job already on an invoice changes what the owner is charged.
		That is an accounting decision (credit note / amend), not a PWA button."""
		_, ro = self._completed("MRREV000005")
		frappe.db.set_value("Repair Order", ro, "billing_status", "Client Billed", update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			mr.request_revision(ro)
		with self.assertRaises(frappe.ValidationError):
			mr.reopen_completed(ro)
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "Completed")

	def test_a_closed_order_cannot_be_un_finished_by_a_plain_status_edit(self):
		"""The state machine has to allow Completed -> In Progress for reopen_completed's own
		save. Every OTHER road to it is shut, or any holder of write permission could
		un-finish a closed order through the generic status endpoint."""
		_, ro = self._completed("MRREV000006")
		doc = frappe.get_doc("Repair Order", ro)
		doc.status = "In Progress"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	# --- evidence photos (Repair Work Photo) ----------------------------------
	def test_photos_are_their_own_table_keyed_to_the_line_they_prove(self):
		"""Proof of work lives beside the estimate, not inside it — and every photo names the
		Service & Parts line it belongs to, which is how the owner knows what changed."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRPHOTO0001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		line = frappe.get_doc("Repair Order", ro).used_items[0]

		mr.save_mr_order(
			repair_order=ro,
			work_photos=[
				{"photo": "/files/before.jpg", "used_item": line.name, "caption": "sebelum"},
				{"photo": "/files/after.jpg", "item": _SERVICE},
			],
		)
		d = mr.get_mr_order_detail(ro)
		album = d["work_photos"]
		self.assertEqual([p["photo"] for p in album], ["/files/before.jpg", "/files/after.jpg"])
		# Both halves of the link are filled in whichever one the caller sent.
		self.assertTrue(all(p["used_item"] == line.name for p in album))
		self.assertTrue(all(p["item"] == _SERVICE for p in album))
		self.assertEqual(album[0]["caption"], "sebelum")
		# The estimate row carries the id the PWA stamps onto each photo.
		self.assertEqual(d["used_items"][0]["name"], line.name)

	def test_a_photo_cannot_claim_a_service_the_owner_is_not_paying_for(self):
		"""A photo captioned with a part that is not on the bill reads as proof of work
		nobody agreed to — worse than no photo at all."""
		self._ensure_service_item()
		self._ensure_item()
		c, _ = self._eir_with_damage("MRPHOTO0002")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		with self.assertRaises(frappe.ValidationError):
			mr.save_mr_order(
				repair_order=ro,
				work_photos=[{"photo": "/files/x.jpg", "item": _ITEM}],  # never on this order
			)

	def test_the_album_is_replaced_whole_so_a_photo_can_be_deleted(self):
		"""Sending the list back is how a wrong photo is removed — a merge would make the one
		screen it is visible on unable to delete it."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRPHOTO0003")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		mr.save_mr_order(repair_order=ro, work_photos=[
			{"photo": "/files/a.jpg", "item": _SERVICE},
			{"photo": "/files/b.jpg", "item": _SERVICE},
		])
		mr.save_mr_order(repair_order=ro, work_photos=[{"photo": "/files/b.jpg", "item": _SERVICE}])
		self.assertEqual(
			[p["photo"] for p in mr.get_mr_order_detail(ro)["work_photos"]], ["/files/b.jpg"]
		)
		# A row whose upload never landed is dropped, not refused — it must not block the
		# save that carries the rest.
		mr.save_mr_order(repair_order=ro, work_photos=[
			{"photo": "/files/b.jpg", "item": _SERVICE}, {"photo": "", "item": _SERVICE},
		])
		self.assertEqual(len(mr.get_mr_order_detail(ro)["work_photos"]), 1)

	def test_photos_outlive_the_frozen_estimate_but_not_the_closed_order(self):
		"""The two tables have different lifetimes, which is the whole reason they are two:
		the estimate freezes when it leaves Draft, the evidence is gathered mid-repair."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRPHOTO0004")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		self._to_in_progress(ro, [{"item": _SERVICE, "quantity": 1}])
		# In Progress: items are frozen, photos are not.
		with self.assertRaises(frappe.ValidationError):
			mr.save_mr_order(repair_order=ro, used_items=[{"item": _SERVICE, "quantity": 2}])
		mr.save_mr_order(repair_order=ro, work_photos=[{"photo": "/files/w.jpg", "item": _SERVICE}])

		mr.save_mr_order(repair_order=ro, submit=True)
		mr.finalize_repair(ro)
		# Closed: the album is part of what the owner was shown, so it closes too.
		with self.assertRaises(frappe.ValidationError):
			mr.save_mr_order(repair_order=ro, work_photos=[])
		self.assertEqual(len(mr.get_mr_order_detail(ro)["work_photos"]), 1)

	# --- rewinding an order that already took its parts -----------------------
	def test_reopen_to_draft_puts_the_parts_back(self):
		"""The cost of issuing early: a rewind has to undo it. The Material Issue is
		CANCELLED rather than reversed with a receipt, so the ledger keeps the issue and
		its undo as one linked pair instead of two movements that happen to net to zero."""
		warehouse = self._ensure_warehouse()
		self._ensure_item()
		self._receive_stock(warehouse, 10)

		c, _ = self._eir_with_damage("MRBACK00001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.save_mr_order(
			repair_order=ro,
			used_items=[{"item": _ITEM, "quantity": 3, "warehouse": warehouse}],
			submit=False,
		)
		mr.publish_to_owner(ro)
		mr.record_decision(ro, "Approved")
		se_name = frappe.db.get_value("Repair Order", ro, "stock_entry")
		self._stock_entries.append(se_name)
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 7.0)

		mr.reopen_to_draft(ro, note="salah part")
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "Draft")
		# Parts back on the shelf, and the link dropped so a re-approval issues afresh.
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 10.0)
		self.assertIsNone(frappe.db.get_value("Repair Order", ro, "stock_entry"))
		self.assertEqual(frappe.db.get_value("Stock Entry", se_name, "docstatus"), 2)

		# And it can go round again — a second, distinct issue.
		mr.publish_to_owner(ro)
		mr.record_decision(ro, "Approved")
		again = frappe.db.get_value("Repair Order", ro, "stock_entry")
		self._stock_entries.append(again)
		self.assertNotEqual(again, se_name)
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 7.0)

	def test_cancelling_an_issued_order_puts_the_parts_back(self):
		"""Same rule from the other exit. Cancel is reached from several places (Desk
		button, ESS endpoint, a raw status edit), so the return lives in the controller's
		before_save rather than in any one of them."""
		warehouse = self._ensure_warehouse()
		self._ensure_item()
		self._receive_stock(warehouse, 10)

		c, _ = self._eir_with_damage("MRCANC00001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.save_mr_order(
			repair_order=ro,
			used_items=[{"item": _ITEM, "quantity": 2, "warehouse": warehouse}],
			submit=False,
		)
		mr.publish_to_owner(ro)
		mr.record_decision(ro, "Approved")
		self._stock_entries.append(frappe.db.get_value("Repair Order", ro, "stock_entry"))
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 8.0)

		doc = frappe.get_doc("Repair Order", ro)
		doc.status = "Cancelled"
		doc.save(ignore_permissions=True)
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 10.0)
		self.assertIsNone(frappe.db.get_value("Repair Order", ro, "stock_entry"))

	def test_out_of_stock_parts_are_dropped_from_the_picker(self):
		"""``_out_of_stock_items`` is what keeps a part out of the M&R picker: a service is
		never in it (nothing to run out of), a part is only absent once the source warehouse
		actually holds it."""
		self._ensure_service_item()
		self._ensure_item()
		warehouse = self._ensure_warehouse()

		# Nothing on hand yet — the part cannot be supplied, the service is unaffected.
		empty = mr._out_of_stock_items(warehouse)
		self.assertIn(_ITEM, empty)
		self.assertNotIn(_SERVICE, empty)

		# Receive stock and the part becomes offerable again.
		self._receive_stock(warehouse, 5)
		empty = mr._out_of_stock_items(warehouse)
		self.assertNotIn(_ITEM, empty)
		self.assertNotIn(_SERVICE, empty)

	def test_no_warehouse_hides_nothing(self):
		"""With no gudang picked yet (a fresh row) stock is unknowable, so parts are left in
		the list rather than all being hidden."""
		self._ensure_item()
		self.assertEqual(mr._out_of_stock_items(None), set())

	def test_part_cannot_exceed_stock_on_hand(self):
		"""Stock must exist before a part can be put on the M&R — and the demand is summed
		per item, so two rows of one part are a single demand of two."""
		self._ensure_item()
		warehouse = self._ensure_warehouse()
		self._receive_stock(warehouse, 1)
		c, _ = self._eir_with_damage("MRSHORT001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)

		with self.assertRaises(frappe.ValidationError):
			mr.save_mr_order(
				repair_order=ro, used_items=[{"item": _ITEM, "quantity": 2, "warehouse": warehouse}],
				submit=False,
			)
		with self.assertRaises(frappe.ValidationError):
			mr.save_mr_order(
				repair_order=ro,
				used_items=[
					{"item": _ITEM, "quantity": 1, "warehouse": warehouse},
					{"item": _ITEM, "quantity": 1, "warehouse": warehouse},
				],
				submit=False,
			)
		# Exactly what is on hand goes through.
		res = mr.save_mr_order(
			repair_order=ro, used_items=[{"item": _ITEM, "quantity": 1, "warehouse": warehouse}],
			submit=False,
		)
		self.assertTrue(res["success"])

	def test_owner_rejected_line_is_not_checked_against_stock(self):
		"""A rejected line is never issued, so it must not be counted against stock either
		— otherwise a rejection would deadlock the completion."""
		self._ensure_item()
		warehouse = self._ensure_warehouse()
		ro = frappe._dict(
			used_items=[frappe._dict(item=_ITEM, quantity=99, decision="Rejected", warehouse=warehouse)],
			container=None,
		)
		mr.assert_stock_available(ro)  # no stock at all, but nothing will be issued

	def test_stock_is_checked_and_issued_per_row_warehouse(self):
		"""Each row names its own gudang: the same part is checked against — and issued out
		of — the warehouse on that row, not one warehouse for the whole order."""
		self._ensure_item()
		wh_a = self._ensure_warehouse()
		wh_b = frappe.get_doc({
			"doctype": "Warehouse", "warehouse_name": "MR Test Store B",
			"company": self.company, "is_group": 0,
		}).insert(ignore_permissions=True).name
		self.addCleanup(
			lambda: frappe.db.exists("Warehouse", wh_b)
			and frappe.delete_doc("Warehouse", wh_b, force=True, ignore_permissions=True)
		)
		self._receive_stock(wh_a, 5)  # stock lives in A only

		c, _ = self._eir_with_damage("MRROWWH0001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)

		# Pointing the row at B (empty) is refused even though A has plenty.
		with self.assertRaises(frappe.ValidationError):
			mr.save_mr_order(
				repair_order=ro,
				used_items=[{"item": _ITEM, "quantity": 1, "warehouse": wh_b}],
				submit=False,
			)
		# Pointing it at A goes through, and the row keeps its own gudang.
		mr.save_mr_order(
			repair_order=ro,
			used_items=[{"item": _ITEM, "quantity": 2, "warehouse": wh_a}],
			submit=False,
		)
		row = frappe.get_doc("Repair Order", ro).used_items[0]
		self.assertEqual(row.warehouse, wh_a)
		self.assertEqual(row.line_type, "Part")
		self.assertEqual(row.on_hand, "5")   # text, so a service can be blank instead of 0

		# Approval issues out of the ROW's own warehouse.
		mr.publish_to_owner(ro)
		mr.record_decision(ro, "Approved")
		se = frappe.get_doc("Stock Entry", frappe.db.get_value("Repair Order", ro, "stock_entry"))
		self.assertEqual(se.items[0].s_warehouse, wh_a)
		self.assertEqual(flt(mr._on_hand(_ITEM, wh_a)), 3.0)  # 5 - 2

	def test_service_row_has_no_warehouse_and_blank_stock(self):
		"""A service cannot run out, so it carries no gudang and its Stok stays EMPTY —
		a 0 there would read as "habis" on a row that can never be."""
		self._ensure_service_item()
		c, _ = self._eir_with_damage("MRSVCWH0001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.save_mr_order(
			repair_order=ro,
			used_items=[{"item": _SERVICE, "quantity": 1, "warehouse": self._ensure_warehouse()}],
			submit=False,
		)
		row = frappe.get_doc("Repair Order", ro).used_items[0]
		self.assertEqual(row.line_type, "Jasa")
		self.assertIsNone(row.warehouse)
		self.assertIn(row.on_hand, (None, ""))
