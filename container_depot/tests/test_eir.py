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


def _ensure_cargo(name):
	if not frappe.db.exists("Cargo", name):
		frappe.get_doc({"doctype": "Cargo", "cargo_name": name, "is_active": 1}).insert(
			ignore_permissions=True, ignore_mandatory=True
		)
	return name


def _make_order_muat(shipper, container, *, truck="B-9001-XY", driver="Budi", phone="08110001", submit=True):
	"""Minimal Order Muat (loading bon) carrying ``container`` — validation + mandatory
	are bypassed; ``submit`` forces docstatus=1 so fetch_voucher accepts it."""
	doc = frappe.get_doc({
		"doctype": "Order Muat", "shipper": shipper,
		"truck_plate": truck, "driver_name": driver, "driver_phone": phone,
		"containers": [{"container": container, "container_no": container}],
	})
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	if submit:
		frappe.db.set_value("Order Muat", doc.name, "docstatus", 1, update_modified=False)
	return doc.name


def _make_order_bongkar(shipper, container, *, ex_vessel="MV TEST", truck="B-2", driver="Andi",
						phone="0833", condition="EMPTY DIRTY", cargo=None, submit=True):
	"""Order Bongkar (unloading bon) carrying ``container`` with its per-container detail
	(truck / driver / driver phone / condition / cargo) on the Container Booking Item row."""
	row = {
		"container": container, "container_no": container,
		"truck_plate": truck, "driver": driver, "driver_phone": phone, "condition": condition,
	}
	if cargo:
		row["cargo"] = cargo
	doc = frappe.get_doc({
		"doctype": "Order Bongkar", "shipper": shipper, "ex_vessel": ex_vessel,
		"containers": [row],
	})
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	if submit:
		frappe.db.set_value("Order Bongkar", doc.name, "docstatus", 1, update_modified=False)
	return doc.name


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
		# Required Inspection Damage Entry fields are defaulted server-side (B2).
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

	def test_create_with_inspector_signature(self):
		# The EIR-creator's virtual signature is stored on the Inspection.
		c = _make_container("EIRC1000007")
		res = eir.create_eir(
			inspection_type="EIR-In", container=c,
			signature="/private/files/sign-2.png",
			lines=[{"item_code": "01", "damage_code": "11"}],
		)
		self.assertEqual(
			frappe.db.get_value("Inspection", res["name"], "inspector_signature"),
			"/private/files/sign-2.png",
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


class TestEirDraft(FrappeTestCase):
	def test_open_creates_then_reopens_same_draft(self):
		# Fetch auto-creates a draft; re-fetching the same container reopens it (dedup).
		c = _make_container("EIRD1000001", serial_no="SER-D1", capacity=24000)
		d1 = eir.open_draft(container_no="EIRD1000001")
		self.assertTrue(d1["inspection"])
		self.assertEqual(d1["container_no"], "EIRD1000001")
		self.assertEqual(d1["serial_no"], "SER-D1")   # header sourced from the master
		self.assertEqual(d1["lines"], [])
		self.assertEqual(d1["photos"], [])
		self.assertEqual(frappe.get_doc("Inspection", d1["inspection"]).docstatus, 0)

		d2 = eir.open_draft(container_no="EIRD1000001")
		self.assertEqual(d2["inspection"], d1["inspection"])
		self.assertEqual(frappe.db.count("Inspection", {"container": c, "docstatus": 0}), 1)

	def test_save_draft_persists_and_reopens(self):
		c = _make_container("EIRD1000002")
		d = eir.open_draft(container_no="EIRD1000002")
		res = eir.save_draft(
			inspection=d["inspection"], inspection_type="EIR-In",
			tank_status="Empty Dirty", vessel="MV X", truck_no="B-9", emkl="PT Y",
			lines=[
				{"item_code": "01", "damage_code": "11", "remarks": "dent"},
				{"item_code": "02"},  # empty -> skipped
			],
			photos=[{"item_code": "01", "photo": "/private/files/p1.jpg"}],
		)
		self.assertEqual(res["damage_rows"], 1)
		self.assertEqual(res["photo_rows"], 1)

		d2 = eir.open_draft(container_no="EIRD1000002")
		self.assertEqual(d2["inspection"], d["inspection"])  # still the same draft
		self.assertEqual(d2["tank_status"], "Empty Dirty")
		self.assertEqual(d2["vessel"], "MV X")
		self.assertEqual(len(d2["lines"]), 1)
		self.assertEqual(d2["lines"][0]["item_code"], "01")
		self.assertEqual(d2["lines"][0]["damage_code"], "11")
		self.assertEqual(len(d2["photos"]), 1)
		self.assertEqual(d2["photos"][0]["photo"], "/private/files/p1.jpg")

	def test_save_draft_replaces_previous_state(self):
		c = _make_container("EIRD1000003")
		d = eir.open_draft(container_no="EIRD1000003")
		eir.save_draft(inspection=d["inspection"], lines=[
			{"item_code": "01", "damage_code": "11"},
			{"item_code": "02", "damage_code": "12"},
		])
		# A second save replaces (does not append) the checklist state.
		eir.save_draft(inspection=d["inspection"], lines=[{"item_code": "03", "repair_code": "33"}])
		d2 = eir.open_draft(container_no="EIRD1000003")
		self.assertEqual(len(d2["lines"]), 1)
		self.assertEqual(d2["lines"][0]["item_code"], "03")

	def test_save_draft_rejects_submitted(self):
		# Once submitted, the EIR is no longer a draft and save_draft must refuse.
		c = _make_container("EIRD1000004", status="Gate_In")
		res = eir.create_eir(inspection_type="EIR-In", container=c,
						   lines=[{"item_code": "01", "damage_code": "11"}], submit=True)
		with self.assertRaises(frappe.ValidationError):
			eir.save_draft(inspection=res["name"], lines=[{"item_code": "02", "damage_code": "12"}])

	def test_save_draft_submit_finalizes(self):
		# The Submit button saves then finalizes: the draft is submitted and its
		# on_submit moves the container; a later fetch starts a fresh draft.
		c = _make_container("EIRD1000005", status="Gate_In")
		d = eir.open_draft(container_no="EIRD1000005")
		res = eir.save_draft(
			inspection=d["inspection"], inspection_type="EIR-In", tank_status="Empty Dirty",
			lines=[{"item_code": "01", "damage_code": "11", "remarks": "dent"}],
			submit=True,
		)
		self.assertEqual(res["docstatus"], 1)
		cont = frappe.db.get_value("Container", c, ["status", "eir_in_date"], as_dict=True)
		self.assertEqual(cont.status, "Inspecting")
		self.assertTrue(cont.eir_in_date)
		d2 = eir.open_draft(container_no="EIRD1000005")
		self.assertNotEqual(d2["inspection"], d["inspection"])

	def test_save_draft_persists_inspector_signature(self):
		# The EIR-creator's virtual signature round-trips through save_draft/open_draft.
		c = _make_container("EIRD1000006")
		d = eir.open_draft(container_no="EIRD1000006")
		eir.save_draft(
			inspection=d["inspection"], inspection_type="EIR-In",
			signature="/private/files/sign-1.png",
			lines=[{"item_code": "01", "damage_code": "11"}],
		)
		d2 = eir.open_draft(container_no="EIRD1000006")
		self.assertEqual(d2["inspector_signature"], "/private/files/sign-1.png")


class TestEirVoucher(FrappeTestCase):
	def test_fetch_voucher_order_muat_for_eir_out(self):
		cust = ensure_test_customer("EIR Voucher Cust")
		c = _make_container("EIRV1000010")
		om = _make_order_muat(cust, c)
		snap = eir.fetch_voucher(om, "EIR-Out", container=c)
		self.assertEqual(snap["voucher_doctype"], "Order Muat")
		self.assertEqual(snap["referred_voucher"], om)
		self.assertEqual(snap["truck_no"], "B-9001-XY")
		self.assertEqual(snap["driver"], "Budi")
		self.assertEqual(snap["driver_phone"], "08110001")
		self.assertEqual(snap["shipper"], cust)

	def test_fetch_voucher_order_bongkar_for_eir_in(self):
		# EIR-In: per-container detail comes from the Order Bongkar's Container Booking Item.
		cust = ensure_test_customer("EIR Voucher Cust")
		_ensure_cargo("Acetone")
		c = _make_container("EIRV1000011")
		ob = _make_order_bongkar(cust, c, truck="B-2", driver="Andi", phone="0833",
								 condition="EMPTY DIRTY", cargo="Acetone")
		snap = eir.fetch_voucher(ob, "EIR-In", container=c)
		self.assertEqual(snap["voucher_doctype"], "Order Bongkar")
		self.assertEqual(snap["shipper"], cust)
		self.assertEqual(snap["truck_no"], "B-2")
		self.assertEqual(snap["driver"], "Andi")
		self.assertEqual(snap["driver_phone"], "0833")
		self.assertEqual(snap["tank_status"], "Empty Dirty")
		self.assertEqual(snap["cargo"], "Acetone")

	def test_fetch_voucher_none_is_empty(self):
		snap = eir.fetch_voucher(None, "EIR-Out")
		self.assertEqual(snap["voucher_doctype"], "Order Muat")
		self.assertIsNone(snap["referred_voucher"])
		self.assertIsNone(snap["shipper"])

	def test_fetch_voucher_not_found_raises(self):
		with self.assertRaises(frappe.ValidationError):
			eir.fetch_voucher("ORD-MT-9999-99999", "EIR-Out")

	def test_fetch_voucher_rejects_unsubmitted(self):
		# Only submitted vouchers may be referenced.
		cust = ensure_test_customer("EIR Voucher Cust")
		c = _make_container("EIRV1000012")
		om = _make_order_muat(cust, c, submit=False)
		with self.assertRaises(frappe.ValidationError):
			eir.fetch_voucher(om, "EIR-Out", container=c)

	def test_fetch_voucher_rejects_container_not_on_voucher(self):
		# The referenced bon must actually carry the inspected container.
		cust = ensure_test_customer("EIR Voucher Cust")
		c1 = _make_container("EIRV1000013")
		c2 = _make_container("EIRV1000014")
		om = _make_order_muat(cust, c1)
		with self.assertRaises(frappe.ValidationError):
			eir.fetch_voucher(om, "EIR-Out", container=c2)

	def test_save_draft_applies_muat_voucher(self):
		# Saving a draft with a referred voucher snapshots truck/driver/shipper onto it.
		cust = ensure_test_customer("EIR Voucher Cust")
		c = _make_container("EIRV1000001")
		om = _make_order_muat(cust, c, truck="B-7", driver="Sari", phone="0822")
		d = eir.open_draft(container_no="EIRV1000001", inspection_type="EIR-Out")
		eir.save_draft(inspection=d["inspection"], inspection_type="EIR-Out",
					   referred_voucher=om, lines=[])
		d2 = eir.open_draft(container_no="EIRV1000001", inspection_type="EIR-Out")
		self.assertEqual(d2["referred_voucher"], om)
		self.assertEqual(d2["truck_no"], "B-7")
		self.assertEqual(d2["driver"], "Sari")
		self.assertEqual(d2["driver_phone"], "0822")
		self.assertEqual(d2["shipper"], cust)


class TestEirCargoAndExVessel(FrappeTestCase):
	def test_draft_cargo_does_not_touch_master(self):
		_ensure_cargo("Acetone")
		_ensure_cargo("Acetic Acid")
		c = _make_container("EIRV2000001", last_cargo="Acetone")
		d = eir.open_draft(container_no="EIRV2000001")
		eir.save_draft(inspection=d["inspection"], cargo="Acetic Acid", lines=[])
		# Draft saved a different cargo, but the master is untouched until submit.
		self.assertEqual(frappe.db.get_value("Container", c, "last_cargo"), "Acetone")

	def test_submit_cargo_writes_master(self):
		_ensure_cargo("Acetone")
		_ensure_cargo("Acetic Acid")
		c = _make_container("EIRV2000002", status="Gate_In", last_cargo="Acetone")
		d = eir.open_draft(container_no="EIRV2000002", inspection_type="EIR-In")
		eir.save_draft(inspection=d["inspection"], inspection_type="EIR-In",
					   tank_status="Empty Dirty", cargo="Acetic Acid",
					   lines=[{"item_code": "01", "damage_code": "11"}], submit=True)
		self.assertEqual(frappe.db.get_value("Container", c, "last_cargo"), "Acetic Acid")

	def test_prefill_returns_container_ex_vessel(self):
		_make_container("EIRV3000001", ex_vessel="MV NEPTUNE")
		data = eir.prefill(container_no="EIRV3000001")
		self.assertEqual(data["ex_vessel"], "MV NEPTUNE")

	def test_order_bongkar_stamps_container_ex_vessel(self):
		from container_depot.operations.doctype.order_bongkar.order_bongkar import (
			_update_container_ex_vessel,
		)
		c = _make_container("EIRV3000002")
		# Not inserted — the writeback only reads ex_vessel + the container rows.
		ob = frappe.get_doc({
			"doctype": "Order Bongkar", "ex_vessel": "MV ATLANTIC",
			"containers": [{"container": c, "container_no": c}],
		})
		_update_container_ex_vessel(ob)
		self.assertEqual(frappe.db.get_value("Container", c, "ex_vessel"), "MV ATLANTIC")

	def test_tank_status_laden_accepted(self):
		c = _make_container("EIRV3000003")
		res = eir.create_eir(inspection_type="EIR-In", container=c, tank_status="Laden",
							 lines=[], submit=False)
		self.assertEqual(frappe.db.get_value("Inspection", res["name"], "tank_status"), "Laden")
