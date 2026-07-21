"""A cancelled bon must not strand the EIR drafts it provisioned.

Two defects met here. The bon's ``on_cancel`` released its Booking Codes but ignored
its EIRs, so a draft kept pointing at a voided voucher; and ``save_draft`` re-resolved
that voucher on every auto-save, so the draft threw "… is not submitted yet" and
became unsavable — while the replacement bon never adopted it (provisioning dedups on
"container already has a draft").
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations import eir
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_container, _make_order_bongkar

CUSTOMER = "EIR Cancel Co"
C_REPOINT = "ECAU1110001"
C_DELETE = "ECAU1110002"
C_KEEP = "ECAU1110003"
CONTAINERS = (C_REPOINT, C_DELETE, C_KEEP)


def _cancel(bon: str):
	"""Void a bon the way the controller leaves it (docstatus 2). The helper-built bons
	skip validation, so a real ``.cancel()`` would trip over their absent Booking Codes;
	the unwind under test only reads docstatus."""
	frappe.db.set_value("Order Bongkar", bon, "docstatus", 2, update_modified=False)


def _draft_eir(container: str, bon: str, *, started=False) -> str:
	doc = frappe.get_doc({
		"doctype": "Inspection",
		"inspection_type": "EIR-In",
		"container": container,
		"inspector": "Administrator",
	})
	eir._apply_voucher(doc, bon)
	doc.insert(ignore_permissions=True)
	if started:
		doc.db_set("work_started_on", frappe.utils.now_datetime())
	return doc.name


def _cleanup():
	inspections = frappe.get_all(
		"Inspection", filters={"container": ("in", CONTAINERS)}, pluck="name"
	)
	if inspections:
		for child in ("Inspection Damage Entry", "Inspection Item Photo", "Inspection Photo"):
			frappe.db.delete(child, {"parent": ("in", inspections)})
		frappe.db.delete("Notification Log", {"document_type": "Inspection", "document_name": ("in", inspections)})
		frappe.db.delete("Inspection", {"name": ("in", inspections)})
	bons = frappe.get_all(
		"Container Booking Item",
		filters={"container": ("in", CONTAINERS), "parenttype": "Order Bongkar"},
		pluck="parent",
		distinct=True,
	)
	if bons:
		frappe.db.delete("Container Booking Item", {"parent": ("in", bons)})
		frappe.db.delete("Notification Log", {"document_type": "Order Bongkar", "document_name": ("in", bons)})
		# Order Bongkar refuses delete_doc ("use Cancel to void it instead").
		frappe.db.delete("Order Bongkar", {"name": ("in", bons)})
	# Both audit logs, not just movements — an EIR/bon writes Container Activity too.
	for log in ("Container Movement", "Container Activity"):
		frappe.db.delete(log, {"container": ("in", CONTAINERS)})
	frappe.db.delete("Container", {"name": ("in", CONTAINERS)})
	if frappe.db.exists("Customer", CUSTOMER):
		frappe.db.delete("Customer", {"name": CUSTOMER})
	frappe.db.commit()


class TestEirCancelledVoucher(FrappeTestCase):
	def setUp(self):
		# Purge before creating, not after: _cleanup removes the Customer built on here.
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)

	def tearDown(self):
		_cleanup()

	def _container(self, cno):
		return _make_container(cno, principal=self.customer)

	# --- the reported symptom -------------------------------------------
	def test_a_draft_left_on_a_cancelled_bon_cannot_be_saved(self):
		"""Why the unwind is mandatory rather than nice-to-have.

		Frappe refuses to save any document linking to a cancelled one, so a draft left
		pointing at a voided bon is unsavable no matter what this app does — skipping the
		voucher re-resolution in ``save_draft`` only swaps the error message. Pinned here
		so nobody "simplifies" the unwind away believing the softer fix was enough.
		"""
		c = self._container(C_KEEP)
		bon = _make_order_bongkar(self.customer, c)
		name = _draft_eir(c, bon, started=True)
		_cancel(bon)

		with self.assertRaises(frappe.exceptions.CancelledLinkError):
			eir.save_draft(inspection=name, inspection_type="EIR-In", referred_voucher=bon,
						   tank_status="Empty Clean", lines="[]", photos="[]")

	def test_the_eir_is_savable_again_once_the_cancel_unwinds_it(self):
		"""The user-facing guarantee: cancelling a bon leaves its EIRs workable."""
		c = self._container(C_KEEP)
		bon = _make_order_bongkar(self.customer, c)
		name = _draft_eir(c, bon, started=True)
		_cancel(bon)
		eir.release_eirs_for_cancelled_order(bon, "EIR-In")

		eir.save_draft(inspection=name, inspection_type="EIR-In",
					   referred_voucher=frappe.db.get_value("Inspection", name, "referred_voucher"),
					   tank_status="Empty Clean", lines="[]", photos="[]")
		self.assertEqual(frappe.db.get_value("Inspection", name, "tank_status"), "Empty Clean")

	def test_switching_to_an_unsubmitted_voucher_is_still_rejected(self):
		"""Only the unchanged echo is exempt — actually attaching a voided bon must
		still fail, or the guard would be gone."""
		c = self._container(C_KEEP)
		good = _make_order_bongkar(self.customer, c)
		name = _draft_eir(c, good, started=True)
		voided = _make_order_bongkar(self.customer, c)
		_cancel(voided)

		with self.assertRaises(frappe.ValidationError):
			eir.save_draft(inspection=name, inspection_type="EIR-In",
						   referred_voucher=voided, lines="[]", photos="[]")

	# --- the unwind, branch by branch ------------------------------------
	def test_cancel_repoints_to_the_replacement_bon(self):
		c = self._container(C_REPOINT)
		old = _make_order_bongkar(self.customer, c)
		name = _draft_eir(c, old, started=True)
		replacement = _make_order_bongkar(self.customer, c)
		_cancel(old)

		eir.release_eirs_for_cancelled_order(old, "EIR-In")
		self.assertEqual(frappe.db.get_value("Inspection", name, "referred_voucher"), replacement)

	def test_cancel_deletes_a_draft_that_was_never_started(self):
		"""save_draft refuses to write before "Mulai", so an unstarted draft provably
		holds no work — it only existed because of this bon."""
		c = self._container(C_DELETE)
		bon = _make_order_bongkar(self.customer, c)
		name = _draft_eir(c, bon, started=False)
		_cancel(bon)

		eir.release_eirs_for_cancelled_order(bon, "EIR-In")
		self.assertFalse(frappe.db.exists("Inspection", name))

	def test_cancel_keeps_started_work_and_drops_only_the_link(self):
		c = self._container(C_KEEP)
		bon = _make_order_bongkar(self.customer, c, truck="B-7788-ZZ", driver="Joko")
		name = _draft_eir(c, bon, started=True)
		_cancel(bon)

		eir.release_eirs_for_cancelled_order(bon, "EIR-In")
		row = frappe.db.get_value("Inspection", name, ["referred_voucher", "truck_no", "driver"], as_dict=True)
		self.assertIsNone(row.referred_voucher)
		# The stamped truck/driver record who actually showed up — losing them would
		# destroy the surveyor's context along with the dead link.
		self.assertEqual(row.truck_no, "B-7788-ZZ")
		self.assertEqual(row.driver, "Joko")
