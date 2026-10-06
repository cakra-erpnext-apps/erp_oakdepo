"""Revisi Data — correcting an EIR that a later EIR has already built on (user, 2026-10-06).

``revert_to_draft`` undoes a submit from the EIR's own snapshot, which is only true for the
newest EIR on the tank: revert the EIR-In after the EIR-Out and the tank that left reads
In_Depot again. So an older EIR is revised in place instead — still Submitted, nothing outside
it touched — and both ways back stop once the visit's storage is invoiced.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, now_datetime, today

from container_depot import storage, storage_charge
from container_depot.container_depot import eir
from container_depot.tests._leak_check import drop_leak_checks
from container_depot.tests.test_gate_out import _container, _eir_out

PREFIX = "RVSD"


def _gate_in(container_no, days_ago, out_days_ago=None):
	"""A visit's Gate Entry, opened ``days_ago`` — what storage reads the stay from."""
	ge = frappe.get_doc({
		"doctype": "Gate Entry",
		"container_no": container_no,
		"status": "Gate_Out_Completed" if out_days_ago is not None else "Gate_In_Completed",
		"gate_in_timestamp": add_days(now_datetime(), -days_ago),
		"gate_out_timestamp": add_days(now_datetime(), -out_days_ago) if out_days_ago is not None else None,
	}).insert(ignore_permissions=True)
	return ge.name


def _visited_tank(no):
	"""A tank that came in three days ago, got its EIR-In, then left on its EIR-Out."""
	c = _container(no, "In_Depot")
	_gate_in(c, 3)
	eir_in = eir.create_eir(
		inspection_type="EIR-In", container=c, tank_status="Empty Clean",
		eir_date=str(add_days(today(), -3)), create_cleaning_order=0, create_repair_order=0, submit=True,
	)["name"]
	eir_out = _eir_out(c)
	return c, eir_in, eir_out


def _bill_visit(container):
	"""Stamp the visit's storage as billed — the watermark alone locks it."""
	storage_charge.sync(container)
	name = frappe.db.get_value("Storage Charge", {"container": container}, "name")
	frappe.db.set_value("Storage Charge", name, "billed_until", today())
	return name


class TestEirRevision(FrappeTestCase):
	def tearDown(self):
		like = ["like", f"{PREFIX}%"]
		frappe.db.delete("Storage Charge", {"container": like})
		frappe.db.delete("Container Activity", {"container": like})
		frappe.db.delete("Container Movement", {"container": like})
		frappe.db.delete("Gate Entry", {"container_no": like})
		frappe.db.delete("Inspection", {"container": like})
		drop_leak_checks(like)
		frappe.db.delete("Container", {"name": like})

	def test_an_old_eir_is_not_reverted_over_a_newer_one(self):
		"""The bug this exists for: the EIR-In's snapshot says In_Depot, but the tank has left."""
		c, eir_in, _out = _visited_tank(f"{PREFIX}0000001")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")

		with self.assertRaisesRegex(frappe.ValidationError, "lebih baru"):
			eir.revert_to_draft(eir_in)
		with self.assertRaisesRegex(frappe.ValidationError, "lebih baru"):
			frappe.get_doc("Inspection", eir_in).cancel()

		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")
		self.assertEqual(frappe.db.get_value("Inspection", eir_in, "docstatus"), 1)

	def test_revisi_data_edits_the_record_and_nothing_else(self):
		c, eir_in, eir_out = _visited_tank(f"{PREFIX}0000002")
		# The newest one goes back to Draft instead — Revisi Data is for the older ones.
		with self.assertRaisesRegex(frappe.ValidationError, "terbaru"):
			eir.open_revision(eir_out)

		eir.open_revision(eir_in)
		doc = frappe.get_doc("Inspection", eir_in)
		doc.remarks = "dikoreksi"
		doc.tank_status = "Empty Dirty"
		doc.save()

		doc.reload()
		self.assertEqual((doc.docstatus, doc.remarks, doc.tank_status), (1, "dikoreksi", "Empty Dirty"))
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")
		# Empty Dirty on submit would file a wash; a revision files nothing.
		self.assertFalse(frappe.db.exists("Cleaning Order", {"container": c}))

		doc.referred_voucher = None
		doc.inspection_type = "EIR-Out"
		with self.assertRaisesRegex(frappe.ValidationError, "tidak boleh mengubah"):
			doc.save()

		eir.close_revision(eir_in)
		doc = frappe.get_doc("Inspection", eir_in)
		doc.remarks = "lagi"
		with self.assertRaises(frappe.ValidationError):
			doc.save()  # closed: back to Frappe's own submitted-document rules

	def test_the_pwa_saves_a_revision_and_simpan_revisi_closes_it(self):
		c, eir_in, _out = _visited_tank(f"{PREFIX}0000003")
		frappe.db.set_value("Inspection", eir_in, {"revision_requested": 1, "revision_requested_by": "Administrator"})
		eir.open_revision(eir_in)
		self.assertEqual(eir.open_draft_by_name(eir_in)["revision"], 1)

		day = str(add_days(today(), -3))
		autosave = eir.save_draft(inspection=eir_in, tank_status="Empty Clean", remarks="pwa", eir_date=day)
		self.assertEqual((autosave["docstatus"], autosave["revision"]), (1, 1))

		eir.save_draft(inspection=eir_in, tank_status="Empty Clean", remarks="pwa final", eir_date=day, submit=1)
		row = frappe.db.get_value(
			"Inspection", eir_in, ["docstatus", "remarks", "revision_open", "revision_requested", "status"], as_dict=True
		)
		self.assertEqual((row.docstatus, row.remarks, row.revision_open, row.revision_requested), (1, "pwa final", 0, 0))
		self.assertEqual(row.status, "Submitted")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")
		with self.assertRaises(frappe.ValidationError):
			eir.open_draft_by_name(eir_in)
		with self.assertRaises(frappe.ValidationError):
			eir.save_draft(inspection=eir_in, tank_status="Empty Clean", eir_date=day)

	def test_an_invoiced_visit_freezes_both_ways_back(self):
		c, eir_in, eir_out = _visited_tank(f"{PREFIX}0000004")
		_bill_visit(c)

		for name in (eir_in, eir_out):
			self.assertTrue(eir.storage_invoice_lock(frappe.get_doc("Inspection", name)))
		with self.assertRaisesRegex(frappe.ValidationError, "diinvoice"):
			eir.revert_to_draft(eir_out)
		with self.assertRaisesRegex(frappe.ValidationError, "diinvoice"):
			eir.open_revision(eir_in)
		with self.assertRaisesRegex(frappe.ValidationError, "diinvoice"):
			eir.request_revision(eir_in, "foto salah")
		# eir_date has always been editable after submit — the loophole this closes.
		doc = frappe.get_doc("Inspection", eir_in)
		doc.eir_date = add_days(today(), -2)
		with self.assertRaisesRegex(frappe.ValidationError, "diinvoice"):
			doc.save()
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")

	def test_eir_date_stays_inside_its_visit_and_the_ledger_follows(self):
		c, eir_in, _out = _visited_tank(f"{PREFIX}0000005")
		storage_charge.sync(c)

		doc = frappe.get_doc("Inspection", eir_in)
		doc.eir_date = add_days(today(), -10)  # before the tank came in
		with self.assertRaisesRegex(frappe.ValidationError, "di dalam kunjungan"):
			doc.save()

		doc.reload()
		doc.eir_date = add_days(today(), -1)
		doc.save()
		date_in = frappe.db.get_value("Storage Charge", {"container": c}, "date_in")
		self.assertEqual(getdate(date_in), getdate(add_days(today(), -1)))

	def test_tolak_revisi_answers_the_request(self):
		c, eir_in, _out = _visited_tank(f"{PREFIX}0000006")
		eir.request_revision(eir_in, "salah foto")
		self.assertEqual(frappe.db.get_value("Inspection", eir_in, "revision_requested_by"), "Administrator")

		with self.assertRaisesRegex(frappe.ValidationError, "Alasan"):
			eir.reject_revision(eir_in, "")
		eir.reject_revision(eir_in, "foto sudah benar")

		row = frappe.db.get_value(
			"Inspection", eir_in, ["revision_requested", "revision_note", "revision_requested_by"], as_dict=True
		)
		self.assertEqual((row.revision_requested, row.revision_note, row.revision_requested_by), (0, None, None))
		with self.assertRaisesRegex(frappe.ValidationError, "Tidak ada permintaan"):
			eir.reject_revision(eir_in, "lagi")


class TestVisitFor(FrappeTestCase):
	"""``storage.visit_for`` — which stay an EIR's date belongs to."""

	def tearDown(self):
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def test_inside_a_window_in_a_gap_and_by_gate_entry(self):
		c = _container(f"{PREFIX}0000101", "In_Depot")
		first = _gate_in(c, 20, out_days_ago=15)
		second = _gate_in(c, 5)

		period, lo, hi = storage.visit_for(c, add_days(today(), -17))
		self.assertEqual(period["ref"], first)
		self.assertEqual((lo, hi), (getdate(add_days(today(), -20)), getdate(add_days(today(), -15))))
		self.assertEqual(storage.visit_for(c, add_days(today(), -2))[0]["ref"], second)
		self.assertIsNone(storage.visit_for(c, add_days(today(), -2))[2])  # still inside

		gap = add_days(today(), -10)
		self.assertEqual(storage.visit_for(c, gap)[0]["ref"], second)  # an EIR-In before arrival
		self.assertEqual(storage.visit_for(c, gap, earlier=True)[0]["ref"], first)  # an EIR-Out after exit
		self.assertEqual(storage.visit_for(c, gap, ref=first)[0]["ref"], first)
