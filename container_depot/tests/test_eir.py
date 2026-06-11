"""Tests for the web-EIR backend (operations.eir core + checklist flow)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations import eir
from container_depot.tests._booking_helpers import make_booking_code
from container_depot.tests.test_api import ensure_test_customer


def _make_container(cno, *, status="Gate_In", **kw):
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": cno,
		"container_type": "ISO Tank",
		"status": status,
		**kw,
	}).insert(ignore_permissions=True).name


class TestEirMasters(FrappeTestCase):
	def test_masters_shape_and_counts(self):
		m = eir.get_eir_masters()
		self.assertEqual(len(m["checklist"]), 50)
		self.assertEqual([m["checklist"][0]["sequence"], m["checklist"][-1]["sequence"]], [1, 50])
		self.assertEqual(m["checklist"][0]["item_name"], "Underside")
		self.assertEqual(len(m["damage_codes"]), 29)
		self.assertEqual(len(m["repair_codes"]), 25)
		# code list carries code + description.
		self.assertIn("code", m["damage_codes"][0])
		self.assertIn("description", m["damage_codes"][0])

	def test_iso6346_parts(self):
		p = eir.iso6346_parts("EIRP1000001")
		self.assertEqual([p["prefix"], p["number"], p["cd"]], ["EIRP", "100000", "1"])
		self.assertEqual(eir.iso6346_parts(""), {"prefix": None, "number": None, "cd": None})


class TestEirPrefill(FrappeTestCase):
	def test_prefill_from_container_no(self):
		# The EIR inspects the container, so the container number is the key — no
		# booking required; principal comes straight from the Container master.
		cust = ensure_test_customer("EIR Prefill Cust")
		c = _make_container("EIRP1000001", principal=cust, serial_no="SER-123",
						   capacity=26000, tare_weight=3800, max_gross_weight=36000)
		data = eir.prefill(container_no="EIRP1000001")
		self.assertEqual(data["container"], c)
		self.assertEqual(data["container_no"], "EIRP1000001")
		self.assertEqual(data["serial_no"], "SER-123")
		self.assertEqual(data["capacity"], 26000)
		self.assertEqual(data["max_gross_weight"], 36000)
		self.assertEqual(data["principal"], cust)
		# Display-only ISO 6346 derive.
		self.assertEqual([data["prefix"], data["number"], data["cd"]], ["EIRP", "100000", "1"])

	def test_prefill_from_booking_code_backcompat(self):
		# A booking_code still resolves the container (automation / back-compat) and
		# enriches direction, but it is no longer the required entry point. Uses its
		# own container number: make_booking_code's Confirmed booking commits, which
		# leaks the container past the per-test rollback and would otherwise collide
		# with the container-keyed test above.
		cust = ensure_test_customer("EIR Prefill Cust")
		c = _make_container("EIRP1000002", principal=cust, serial_no="SER-456")
		code = make_booking_code(customer=cust, container_no="EIRP1000002", container=c)
		data = eir.prefill(booking_code=code.name)
		self.assertEqual(data["container"], c)
		self.assertEqual(data["serial_no"], "SER-456")
		self.assertEqual(data["direction"], "Tank In")
		self.assertEqual(data["principal"], cust)

	def test_prefill_bad_container_raises(self):
		with self.assertRaises(frappe.ValidationError):
			eir.prefill(container_no="NOPE-NO-SUCH-CONTAINER")

	def test_prefill_bad_code_raises(self):
		with self.assertRaises(frappe.ValidationError):
			eir.prefill(booking_code="OAK-DOES-NOT-EXIST")


class TestEirCreate(FrappeTestCase):
	def test_draft_only_filled_lines_become_damage_entries(self):
		c = _make_container("EIRC1000001")
		lines = [
			{"item_code": "01", "damage_code": "11", "remarks": "dent on underside"},  # filled
			{"item_code": "02"},                                                       # empty -> skip
			{"item_code": "24", "repair_code": "33"},                                  # repair only -> filled
		]
		res = eir.create_eir(inspection_type="EIR-In", container=c, tank_status="Empty Dirty",
						   lines=lines, submit=False)
		self.assertTrue(res["success"])
		self.assertEqual(res["damage_rows"], 2)
		doc = frappe.get_doc("Inspection", res["name"])
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual(len(doc.damage_log), 2)
		# Required Damage Entry fields are defaulted server-side (B2).
		for d in doc.damage_log:
			self.assertEqual(d.severity, "Minor")
			self.assertTrue(d.damage_description)
		first = doc.damage_log[0]
		self.assertEqual(first.checklist_item, "01")
		self.assertEqual(first.component, "1. Underside")
		self.assertEqual(first.damage_description, "dent on underside")

	def test_submit_moves_container_via_controller(self):
		# EIR-In submit must route the Container through Inspection.on_submit, NOT
		# via any status code in the endpoint.
		c = _make_container("EIRC1000002", status="Gate_In")
		res = eir.create_eir(
			inspection_type="EIR-In", container=c, tank_status="Empty Dirty",
			truck_no="B-1234-XY", emkl="PT EMKL", remarks="ok",
			lines=[{"item_code": "11", "damage_code": "12", "remarks": "broken"}],
			submit=True,
		)
		doc = frappe.get_doc("Inspection", res["name"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.has_damage, 1)
		self.assertEqual(doc.truck_no, "B-1234-XY")
		self.assertEqual(doc.emkl, "PT EMKL")
		cont = frappe.db.get_value("Container", c, ["status", "eir_in_date"], as_dict=True)
		self.assertEqual(cont.status, "Inspecting")
		self.assertTrue(cont.eir_in_date)

	def test_has_damage_false_for_acceptable_or_repair_only(self):
		c = _make_container("EIRC1000003")
		lines = [
			{"item_code": "01", "damage_code": "v"},   # Acceptable — stored, not "damage"
			{"item_code": "02", "repair_code": "38"},  # repair only — not "damage"
		]
		res = eir.create_eir(inspection_type="EIR-In", container=c, lines=lines, submit=False)
		self.assertEqual(res["damage_rows"], 2)
		self.assertEqual(frappe.get_doc("Inspection", res["name"]).has_damage, 0)

	def test_create_with_item_photos(self):
		c = _make_container("EIRC1000005")
		res = eir.create_eir(
			inspection_type="EIR-In", container=c,
			lines=[{"item_code": "01", "damage_code": "11", "remarks": "dent"}],
			photos=[
				{"item_code": "01", "photo": "/private/files/a.jpg"},
				{"item_code": "01", "photo": "/private/files/b.jpg"},  # multi per item
				{"item_code": "03", "photo": "/private/files/c.jpg"},
				{"item_code": "03", "photo": ""},                      # blank -> skipped
			],
			submit=False,
		)
		self.assertEqual(res["photo_rows"], 3)
		doc = frappe.get_doc("Inspection", res["name"])
		self.assertEqual(len(doc.item_photos), 3)
		self.assertEqual(doc.item_photos[0].checklist_item, "01")
		self.assertEqual(doc.item_photos[0].photo, "/private/files/a.jpg")
		self.assertEqual(doc.item_photos[2].checklist_item, "03")

	def test_create_rejects_unknown_photo_item(self):
		c = _make_container("EIRC1000006")
		with self.assertRaises(frappe.ValidationError):
			eir.create_eir(
				inspection_type="EIR-In", container=c,
				photos=[{"item_code": "99", "photo": "/private/files/x.jpg"}],
				submit=False,
			)

	def test_create_respects_permissions(self):
		# No ignore_permissions on insert: a user without Inspection create is rejected.
		c = _make_container("EIRC1000004")
		email = "eir-noperm@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User", "email": email, "first_name": "NoPerm",
				"send_welcome_email": 0, "roles": [],
			}).insert(ignore_permissions=True)
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				eir.create_eir(
					inspection_type="EIR-In", container=c,
					lines=[{"item_code": "01", "damage_code": "11"}], submit=False,
				)
		finally:
			frappe.set_user("Administrator")
