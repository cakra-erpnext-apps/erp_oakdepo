"""Cleaning Order flow (container_depot.cleaning): the order carries the chosen services
(tariff + labour), the remarks and the surveyor's signature.

Flow: order (Pending) -> start_cleaning (In_Progress) -> save_cleaning_order(submit) ->
Completed, which parks the tank in the Cleaning Bay. The submitted Completed order is
itself the TANK OUT proof. A normal order cannot be submitted before it is started.

Submitting a Cleaning Order commits (controller drives the container), so created docs
are removed explicitly after each test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import cleaning
from container_depot.container_depot.exceptions import AlreadySettled
from container_depot.tests.test_eir import _ensure_cargo, _make_container


class TestCleaningOrderFlow(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._orders = []
		self._cargos = []
		self._items = []

	def tearDown(self):
		for o in self._orders:
			frappe.db.delete("Cleaning Order", {"name": o})
		for c in self._containers:
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Inspection", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		for cargo in self._cargos:
			frappe.db.delete("Cargo", {"name": cargo})
		for item in self._items:
			frappe.db.delete("Item Price", {"item_code": item})
			frappe.db.delete("Item", {"name": item})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno, **kw):
		c = _make_container(cno, **kw)
		self._containers.append(c)
		return c

	def _cargo(self, name):
		self._cargos.append(name)
		return _ensure_cargo(name)

	def _eir(self, container, cargo, eir_date, inspection_type="EIR-In"):
		"""A submitted EIR carrying ``cargo`` — docstatus is flipped directly so the
		controller's container writeback stays out of this query-level test."""
		doc = frappe.get_doc({
			"doctype": "Inspection", "container": container, "inspection_type": inspection_type,
			"eir_date": eir_date, "cargo": self._cargo(cargo),
		}).insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.set_value("Inspection", doc.name, "docstatus", 1)
		return doc.name

	def _order(self, container, **kw):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Pending", **kw,
		}).insert(ignore_permissions=True)
		self._orders.append(co.name)
		return co.name

	# --- what a chosen service is priced at -----------------------------------
	def test_service_row_carries_both_tariffs_from_the_price_list(self):
		"""A cleaning line carries the two prices the rate card states — the service tariff and
		its labour tariff — each as it stands. Neither is multiplied by anything here, and
		neither is folded into the other: billing settles labour on its own invoice line."""
		from frappe.utils import flt

		item, price_list = "CLEAN-MHR-TEST", "Standard Selling"
		tariff, labour = 200.0, 50.0
		if not frappe.db.exists("Item", item):
			frappe.get_doc({
				"doctype": "Item", "item_code": item, "item_name": "Cleaning Manhour Test",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
				"stock_uom": "Nos", "is_stock_item": 0, "is_sales_item": 1,
			}).insert(ignore_permissions=True)
		self._items.append(item)
		frappe.get_doc({
			"doctype": "Item Price", "item_code": item, "price_list": price_list,
			"selling": 1, "price_list_rate": tariff, "manhour_rate": labour,
		}).insert(ignore_permissions=True)

		cno = self._container("MHRCLEAN001")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": cno, "status": "Service Setup",
			"cleaning_services": [{"cleaning_item": item}],
		}).insert(ignore_permissions=True)
		self._orders.append(co.name)
		row = co.cleaning_services[0]
		self.assertAlmostEqual(flt(row.rate), tariff, msg="tarif service dari price list")
		self.assertAlmostEqual(flt(row.manhour_rate), labour, msg="tarif manhour dari price list")
		self.assertAlmostEqual(flt(co.cleaning_total), tariff)
		self.assertAlmostEqual(flt(co.manhour_charge_total), labour, msg="apa adanya, tanpa dikali")

	# --- masters / detail -----------------------------------------------------
	def test_detail_remarks_start_blank(self):
		# No boiler-plate template is pre-filled into Catatan/remarks on a fresh order.
		c = self._container("CLNREM00001")
		co = self._order(c)
		d = cleaning.get_cleaning_order_detail(co)
		self.assertEqual(d["remarks"], "")

	def test_detail_returns_tank_spec(self):
		c = self._container("CLNDET00001", container_type="ISO Tank", tare_weight=3800, capacity=26000)
		co = self._order(c)
		d = cleaning.get_cleaning_order_detail(co)
		self.assertEqual(d["container"], c)
		self.assertEqual(d["tank_type"], "ISO Tank")
		self.assertEqual(d["tare"], 3800)
		self.assertEqual(d["capacity"], 26000)
		self.assertEqual(str(d["date_of_issue"]), frappe.utils.today())

	def test_detail_carries_cleaning_instructions(self):
		"""Instruksi yang ditulis Admin Ops di order harus sampai ke PWA operator."""
		co = self._order(self._container("CLNINSTR001"))
		frappe.db.set_value("Cleaning Order", co, "cleaning_instructions", "Bilas 2x, jangan pakai deterjen.")
		self.assertEqual(
			cleaning.get_cleaning_order_detail(co)["cleaning_instructions"],
			"Bilas 2x, jangan pakai deterjen.",
		)

	def test_cargo_history_empty_ok(self):
		c = self._container("CLNCARGO001")
		self.assertEqual(cleaning.cargo_history(c), [])

	def test_cargo_history_comes_from_submitted_eirs(self):
		"""Riwayat cargo dibaca langsung dari EIR yang sudah disubmit — terbaru dulu."""
		c = self._container("CLNCARGO002")
		self._eir(c, "CLN Toluene", "2026-01-10")
		self._eir(c, "CLN Methanol", "2026-03-05")
		self.assertEqual(
			cleaning.cargo_history(c),
			[{"cargo": "CLN Methanol", "date": "2026-03-05"},
			 {"cargo": "CLN Toluene", "date": "2026-01-10"}],
		)

	def test_cargo_history_skips_drafts_and_collapses_repeats(self):
		"""EIR draft tidak dihitung; EIR-Out yang membawa cargo yang sama tidak diulang."""
		c = self._container("CLNCARGO003")
		self._eir(c, "CLN Toluene", "2026-01-10")
		self._eir(c, "CLN Toluene", "2026-01-12", inspection_type="EIR-Out")
		frappe.get_doc({
			"doctype": "Inspection", "container": c, "inspection_type": "EIR-In",
			"eir_date": "2026-02-01", "cargo": self._cargo("CLN Xylene"),
		}).insert(ignore_permissions=True, ignore_mandatory=True)  # draft — must be ignored
		self.assertEqual(
			cleaning.cargo_history(c), [{"cargo": "CLN Toluene", "date": "2026-01-12"}],
		)

	def test_cargo_history_respects_limit(self):
		c = self._container("CLNCARGO004")
		for i, cargo in enumerate(["CLN A", "CLN B", "CLN C"], start=1):
			self._eir(c, cargo, f"2026-01-0{i}")
		self.assertEqual([h["cargo"] for h in cleaning.cargo_history(c, limit=2)], ["CLN C", "CLN B"])

	# --- lifecycle ------------------------------------------------------------
	def test_start_marks_in_progress(self):
		c = self._container("CLNSTART001", status="In_Depot")
		co = self._order(c)
		cleaning.start_cleaning(co)
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "status"), "In_Progress")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")

	def test_start_stamps_the_operator_who_pressed_mulai(self):
		"""Assigned To records who is doing the work — the PWA account that started it, not
		whoever raised the order in Desk."""
		c = self._container("CLNSTART002", status="In_Depot")
		co = self._order(c)
		self.assertFalse(frappe.db.get_value("Cleaning Order", co, "assigned_to"))
		cleaning.start_cleaning(co)
		self.assertEqual(
			frappe.db.get_value("Cleaning Order", co, "assigned_to"), frappe.session.user
		)

	def test_field_submit_sends_for_review_instead_of_finishing(self):
		"""The PWA's "selesai" hands the order to Admin Ops — it does not finalize it.

		Until the Desk Submit lands the order is still open, so the tank stays In_Depot."""
		c = self._container("CLNNOST0001", status="In_Depot")
		co = self._order(c)
		res = cleaning.save_cleaning_order(cleaning_order=co, submit=True)
		self.assertEqual(res["docstatus"], 0)
		self.assertEqual(res["status"], "Pending Review")
		self.assertTrue(res["pending_review"])
		# Who did the work, and when it ended, are recorded now — the reviewer's Submit
		# must not claim them.
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "completed_by"), frappe.session.user)
		self.assertTrue(frappe.db.get_value("Cleaning Order", co, "cleaning_end"))
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")

	def test_review_queue_lists_what_is_waiting_for_admin_ops(self):
		c = self._container("CLNREVQ0001", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.save_cleaning_order(cleaning_order=co, submit=True)
		names = {i["name"] for i in cleaning.list_review_cleaning_orders(page_length=500)["items"]}
		self.assertIn(co, names)
		# ...and it has left the operator worklist.
		open_names = {i["name"] for i in cleaning.list_open_cleaning_orders(page_length=500)["items"]}
		self.assertNotIn(co, open_names)

	def test_withdraw_review_returns_the_order_to_the_operator(self):
		c = self._container("CLNWDRW0001", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.start_cleaning(co)
		cleaning.save_cleaning_order(cleaning_order=co, submit=True)
		cleaning.withdraw_review(co)
		row = frappe.db.get_value("Cleaning Order", co, ["status", "cleaning_end"], as_dict=True)
		self.assertEqual(row.status, "In_Progress")
		self.assertFalse(row.cleaning_end, "the finish time is re-taken on the next send")

	def test_admin_ops_submit_completes_and_stamps_a_missing_start(self):
		# Submit (Desk, Admin Ops) IS the finish action. An order that never went through the
		# operator route — work done off-system — completes and has its missing cleaning_start
		# stamped, not refused.
		c = self._container("CLNNOST0002", status="In_Depot")
		co = self._order(c)
		doc = frappe.get_doc("Cleaning Order", co)
		doc.submit()
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "status"), "Completed")
		self.assertTrue(frappe.db.get_value("Cleaning Order", co, "cleaning_start"))

	def test_start_then_submit_completes(self):
		# OAK1 has a seeded Cleaning Bay zone (OAK1-CBAY).
		c = self._container("CLNFULL0001", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.start_cleaning(co)
		res = cleaning.save_cleaning_order(
			cleaning_order=co, cleaning_type="Steam Wash", remarks="bersih", submit=True,
		)
		self.assertEqual(res["status"], "Pending Review")
		# Admin Ops reviews on the Desk; THAT submit is what completes the order.
		frappe.get_doc("Cleaning Order", co).submit()

		cont = frappe.db.get_value("Container", c, ["status"], as_dict=True)
		self.assertEqual(cont.status, "Available")
		# The submitted Completed order IS the TANK OUT proof Order Muat gates on.
		self.assertTrue(frappe.db.exists(
			"Cleaning Order", {"container": c, "status": "Completed", "docstatus": 1}
		))
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "remarks"), "bersih")

	def test_revert_to_draft_reopens_a_completed_order(self):
		"""Admin Ops acting on a revision request: the SAME order goes back to In_Progress —
		editable, back in the PWA worklist — and the tank is held again."""
		c = self._container("CLNRVRT0001", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.start_cleaning(co)
		cleaning.save_cleaning_order(cleaning_order=co, submit=True)
		frappe.get_doc("Cleaning Order", co).submit()
		cleaning.request_revision(co, reason="foto QC kurang")
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "revision_requested"), 1)

		cleaning.revert_to_draft(co)
		row = frappe.db.get_value(
			"Cleaning Order", co,
			["docstatus", "status", "cleaning_end", "revision_requested"], as_dict=True,
		)
		self.assertEqual(row.docstatus, 0)
		self.assertEqual(row.status, "In_Progress")
		self.assertFalse(row.cleaning_end, "the finish time is re-taken on the next sign-off")
		self.assertFalse(row.revision_requested, "the request has been actioned")
		# Open work again -> the tank is not free to leave.
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")

	def test_revert_refuses_an_order_that_is_already_invoiced(self):
		c = self._container("CLNRVRT0002", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.start_cleaning(co)
		cleaning.save_cleaning_order(cleaning_order=co, submit=True)
		frappe.get_doc("Cleaning Order", co).submit()
		frappe.db.set_value("Cleaning Order", co, "sales_invoice", "ACC-SINV-TEST-0001")
		with self.assertRaises(frappe.ValidationError):
			cleaning.revert_to_draft(co)
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "docstatus"), 1)

	def test_finished_order_refuses_a_late_save_as_AlreadySettled(self):
		# The offline queue's worst case: the surveyor signed off in a dead spot, and by the
		# time the handset found signal somebody had already completed the same order on the
		# Desk. The refusal has to be `AlreadySettled` and not a plain ValidationError —
		# Frappe puts the class name in the response as `exc_type`, and that is what tells
		# the PWA to park the row as "sudah ditangani" instead of retrying it for ever.
		# See container_depot/exceptions.py and frontend/src/data/outbox.js.
		c = self._container("CLNSETTLED1", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.start_cleaning(co)
		cleaning.save_cleaning_order(cleaning_order=co, cleaning_type="Steam Wash", submit=True)
		frappe.get_doc("Cleaning Order", co).submit()  # Admin Ops finalizes on the Desk

		with self.assertRaises(AlreadySettled):
			cleaning.save_cleaning_order(cleaning_order=co, remarks="dari HP yang offline")
		# Still a ValidationError, so every existing caller and test keeps working.
		with self.assertRaises(frappe.ValidationError):
			cleaning.start_cleaning(co)

	def test_save_draft_keeps_order_open(self):
		c = self._container("CLNDRAFT001", status="In_Depot")
		co = self._order(c)
		cleaning.start_cleaning(co)
		res = cleaning.save_cleaning_order(cleaning_order=co, remarks="draft note", submit=False)
		self.assertEqual(res["docstatus"], 0)
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "remarks"), "draft note")
