"""Tests for the web-EIR backend (operations.eir core + checklist flow)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations import eir
from container_depot.tests._booking_helpers import make_booking_code
from container_depot.tests.test_api import ensure_test_customer


def _make_container(cno, *, status="In_Depot", **kw):
	kw.setdefault("principal", ensure_test_customer("EIR Test Principal"))
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
		# Positional taxonomy (v0_39): 138 parts across Front .. Internal Shell.
		m = eir.get_eir_masters()
		self.assertEqual(len(m["checklist"]), 138)
		self.assertEqual([m["checklist"][0]["sequence"], m["checklist"][-1]["sequence"]], [1, 138])
		self.assertEqual(m["checklist"][0]["item_name"], "Front Top Rail")
		self.assertEqual(len(m["damage_codes"]), 36)
		self.assertEqual(len(m["repair_codes"]), 25)
		# code list carries code + description.
		self.assertIn("code", m["damage_codes"][0])
		self.assertIn("description", m["damage_codes"][0])

	def test_checklist_carries_per_part_codes(self):
		"""Every part narrows the PWA pickers to the codes valid for it (workbook-seeded),
		with the primary repair action first."""
		m = eir.get_eir_masters()
		self.assertTrue(all(c["damage_codes"] and c["repair_codes"] for c in m["checklist"]))
		front_top_rail = m["checklist"][0]
		self.assertIn("11", front_top_rail["damage_codes"])  # Dented
		self.assertEqual(front_top_rail["repair_codes"][0], "30")  # Straighten (primary)
		self.assertIn("X", front_top_rail["repair_codes"])  # No Action (optional, last)

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
		c = _make_container("EIRC1000002", status="In_Depot")
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
		self.assertEqual(cont.status, "In_Depot")
		self.assertTrue(cont.eir_in_date)

	def test_acceptable_skipped_and_repair_only_not_damage(self):
		c = _make_container("EIRC1000003")
		lines = [
			{"item_code": "01", "damage_code": "v"},   # Acceptable + No Action (default) — NOT stored
			{"item_code": "02", "repair_code": "38"},  # repair only — stored, but not "damage"
		]
		res = eir.create_eir(inspection_type="EIR-In", container=c, lines=lines, submit=False)
		self.assertEqual(res["damage_rows"], 1)
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
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
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
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
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
		c = _make_container("EIRD1000004", status="In_Depot")
		res = eir.create_eir(inspection_type="EIR-In", container=c,
						   lines=[{"item_code": "01", "damage_code": "11"}], submit=True)
		with self.assertRaises(frappe.ValidationError):
			eir.save_draft(inspection=res["name"], lines=[{"item_code": "02", "damage_code": "12"}])

	def test_save_draft_submit_finalizes(self):
		# The Submit button saves then finalizes: the draft is submitted and its
		# on_submit moves the container; a later fetch starts a fresh draft.
		c = _make_container("EIRD1000005", status="In_Depot")
		d = eir.open_draft(container_no="EIRD1000005")
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
		res = eir.save_draft(
			inspection=d["inspection"], inspection_type="EIR-In", tank_status="Empty Dirty",
			lines=[{"item_code": "01", "damage_code": "11", "remarks": "dent"}],
			submit=True,
		)
		self.assertEqual(res["docstatus"], 1)
		cont = frappe.db.get_value("Container", c, ["status", "eir_in_date"], as_dict=True)
		self.assertEqual(cont.status, "In_Depot")
		self.assertTrue(cont.eir_in_date)
		d2 = eir.open_draft(container_no="EIRD1000005")
		self.assertNotEqual(d2["inspection"], d["inspection"])

	def test_save_draft_persists_inspector_signature(self):
		# The EIR-creator's virtual signature round-trips through save_draft/open_draft.
		c = _make_container("EIRD1000006")
		d = eir.open_draft(container_no="EIRD1000006")
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
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
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
		eir.save_draft(inspection=d["inspection"], inspection_type="EIR-Out",
					   referred_voucher=om, lines=[])
		d2 = eir.open_draft(container_no="EIRV1000001", inspection_type="EIR-Out")
		self.assertEqual(d2["referred_voucher"], om)
		self.assertEqual(d2["truck_no"], "B-7")
		self.assertEqual(d2["driver"], "Sari")
		self.assertEqual(d2["driver_phone"], "0822")
		self.assertEqual(d2["shipper"], cust)


class TestEirAutoVoucher(FrappeTestCase):
	"""Auto-reference the latest submitted bon on a fresh EIR draft (no manual retype)."""

	def test_open_draft_auto_refs_latest_bongkar_for_eir_in(self):
		cust = ensure_test_customer("EIR Voucher Cust")
		_ensure_cargo("Toluene")
		c = _make_container("EIRA1000001")
		ob = _make_order_bongkar(cust, c, truck="B-AUTO", driver="Dewi", phone="0855",
								 condition="EMPTY DIRTY", cargo="Toluene")
		d = eir.open_draft(container_no="EIRA1000001", inspection_type="EIR-In")
		self.assertEqual(d["referred_voucher"], ob)
		self.assertEqual(d["voucher_doctype"], "Order Bongkar")
		self.assertEqual(d["truck_no"], "B-AUTO")
		self.assertEqual(d["driver"], "Dewi")
		self.assertEqual(d["driver_phone"], "0855")
		self.assertEqual(d["shipper"], cust)
		self.assertEqual(d["tank_status"], "Empty Dirty")
		self.assertEqual(d["cargo"], "Toluene")

	def test_open_draft_auto_refs_latest_muat_for_eir_out(self):
		cust = ensure_test_customer("EIR Voucher Cust")
		c = _make_container("EIRA1000002")
		om = _make_order_muat(cust, c, truck="B-OUT", driver="Eka", phone="0866")
		d = eir.open_draft(container_no="EIRA1000002", inspection_type="EIR-Out")
		self.assertEqual(d["referred_voucher"], om)
		self.assertEqual(d["voucher_doctype"], "Order Muat")
		self.assertEqual(d["truck_no"], "B-OUT")
		self.assertEqual(d["driver"], "Eka")

	def test_open_draft_picks_newest_submitted_order(self):
		cust = ensure_test_customer("EIR Voucher Cust")
		c = _make_container("EIRA1000003")
		old = _make_order_bongkar(cust, c, truck="B-OLD", driver="Old")
		new = _make_order_bongkar(cust, c, truck="B-NEW", driver="New")
		frappe.db.set_value("Order Bongkar", old, "creation", "2026-01-01 00:00:00", update_modified=False)
		frappe.db.set_value("Order Bongkar", new, "creation", "2026-02-01 00:00:00", update_modified=False)
		d = eir.open_draft(container_no="EIRA1000003", inspection_type="EIR-In")
		self.assertEqual(d["referred_voucher"], new)
		self.assertEqual(d["truck_no"], "B-NEW")

	def test_open_draft_ignores_unsubmitted_order(self):
		cust = ensure_test_customer("EIR Voucher Cust")
		c = _make_container("EIRA1000004")
		_make_order_bongkar(cust, c, submit=False)  # draft bon — must be ignored
		d = eir.open_draft(container_no="EIRA1000004", inspection_type="EIR-In")
		self.assertIsNone(d["referred_voucher"])

	def test_open_draft_takes_depot_from_voucher_booking(self):
		# The EIR's depot comes from the bon's booking (Container Booking.depot), not the
		# Container master — proven by making them differ.
		from container_depot.tests.test_api import ensure_test_branch
		br = ensure_test_branch()
		for dep in ("EIRADEP1", "EIRADEP2"):
			if not frappe.db.exists("Depot", dep):
				frappe.get_doc({
					"doctype": "Depot", "depot_code": dep, "depot_name": dep,
					"branch": br, "is_active": 1,
				}).insert(ignore_permissions=True)
		cust = ensure_test_customer("EIR Voucher Cust")
		c = _make_container("EIRA1000006", depot="EIRADEP1")
		code = make_booking_code(customer=cust, container_no=c, direction="Tank In", container=c)
		frappe.db.set_value("Container Booking", code.booking, "depot", "EIRADEP2")
		ob = _make_order_bongkar(cust, c)
		frappe.db.set_value("Order Bongkar", ob, "booking", code.booking)
		d = eir.open_draft(container_no="EIRA1000006", inspection_type="EIR-In")
		self.assertEqual(d["referred_voucher"], ob)
		self.assertEqual(d["depot"], "EIRADEP2")

	def test_open_draft_does_not_override_existing_draft(self):
		# "Sekali saja": a newer order created after the draft exists must NOT overwrite it.
		cust = ensure_test_customer("EIR Voucher Cust")
		c = _make_container("EIRA1000005")
		first = _make_order_bongkar(cust, c, truck="B-FIRST", driver="First")
		d1 = eir.open_draft(container_no="EIRA1000005", inspection_type="EIR-In")
		self.assertEqual(d1["referred_voucher"], first)
		second = _make_order_bongkar(cust, c, truck="B-SECOND", driver="Second")
		frappe.db.set_value("Order Bongkar", second, "creation", "2030-01-01 00:00:00", update_modified=False)
		d2 = eir.open_draft(container_no="EIRA1000005", inspection_type="EIR-In")
		self.assertEqual(d2["inspection"], d1["inspection"])  # same draft reopened
		self.assertEqual(d2["referred_voucher"], first)  # not overwritten
		self.assertEqual(d2["truck_no"], "B-FIRST")


class TestEirCargoAndExVessel(FrappeTestCase):
	def test_draft_cargo_does_not_touch_master(self):
		_ensure_cargo("Acetone")
		_ensure_cargo("Acetic Acid")
		c = _make_container("EIRV2000001", last_cargo="Acetone")
		d = eir.open_draft(container_no="EIRV2000001")
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
		eir.save_draft(inspection=d["inspection"], cargo="Acetic Acid", lines=[])
		# Draft saved a different cargo, but the master is untouched until submit.
		self.assertEqual(frappe.db.get_value("Container", c, "last_cargo"), "Acetone")

	def test_submit_cargo_writes_master(self):
		_ensure_cargo("Acetone")
		_ensure_cargo("Acetic Acid")
		c = _make_container("EIRV2000002", status="In_Depot", last_cargo="Acetone")
		d = eir.open_draft(container_no="EIRV2000002", inspection_type="EIR-In")
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
		eir.save_draft(inspection=d["inspection"], inspection_type="EIR-In",
					   tank_status="Empty Dirty", cargo="Acetic Acid",
					   lines=[{"item_code": "01", "damage_code": "11"}], submit=True)
		self.assertEqual(frappe.db.get_value("Container", c, "last_cargo"), "Acetic Acid")

	def test_eir_in_submit_writes_eir_in_date(self):
		c = _make_container("EIRV2000020", status="In_Depot")
		d = eir.open_draft(container_no="EIRV2000020", inspection_type="EIR-In")
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
		eir.save_draft(inspection=d["inspection"], inspection_type="EIR-In",
					   tank_status="Empty Dirty", lines=[], submit=True)
		self.assertIsNotNone(frappe.db.get_value("Container", c, "eir_in_date"))

	def test_eir_out_submit_writes_eir_out_date(self):
		# EIR-Out submit now records the container's gate-out date (was never written).
		c = _make_container("EIRV2000021", status="Available")
		d = eir.open_draft(container_no="EIRV2000021", inspection_type="EIR-Out")
		eir.start_eir(d["inspection"])  # editing requires an explicit Mulai first
		eir.save_draft(inspection=d["inspection"], inspection_type="EIR-Out",
					   tank_status="Empty Clean", lines=[], submit=True)
		self.assertIsNotNone(frappe.db.get_value("Container", c, "eir_out_date"))

	def test_prefill_returns_container_ex_vessel(self):
		_make_container("EIRV3000001", ex_vessel="MV NEPTUNE")
		data = eir.prefill(container_no="EIRV3000001")
		self.assertEqual(data["ex_vessel"], "MV NEPTUNE")

	def test_prefill_returns_eir_in_date_as_date(self):
		# The PWA header shows EIR-In Date (from the Container master) — date-only.
		c = _make_container("EIRV3000010")
		frappe.db.set_value("Container", c, "eir_in_date", "2026-06-12 09:16:53")
		data = eir.prefill(container_no="EIRV3000010")
		self.assertEqual(data["eir_in_date"], "2026-06-12")

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


class TestEirHistory(FrappeTestCase):
	def test_my_history_scoping_order_search_pagination(self):
		me = "eir-hist-me@example.com"
		other = "eir-hist-other@example.com"
		for u in (me, other):
			if not frappe.db.exists("User", u):
				frappe.get_doc({"doctype": "User", "email": u, "first_name": "Hist",
								"send_welcome_email": 0, "roles": []}).insert(ignore_permissions=True)

		def mine(cno, when):
			res = eir.create_eir(inspection_type="EIR-In", container=_make_container(cno), lines=[])
			frappe.db.set_value("Inspection", res["name"],
								{"owner": me, "creation": when}, update_modified=False)
			return res["name"]

		mine("EIRH1000001", "2026-01-01 10:00:00")
		mine("EIRH1000002", "2026-01-02 10:00:00")
		mine("EIRH1000003", "2026-01-03 10:00:00")
		# Someone else's EIR must never surface in my history.
		ot = eir.create_eir(inspection_type="EIR-In", container=_make_container("EIRH1000099"), lines=[])
		frappe.db.set_value("Inspection", ot["name"], "owner", other, update_modified=False)

		# Scoping + newest-first.
		res = eir.list_my_eirs(user=me)
		self.assertEqual(res["total"], 3)
		cnos = [r["container_no"] for r in res["items"]]
		self.assertEqual(cnos, ["EIRH1000003", "EIRH1000002", "EIRH1000001"])
		self.assertNotIn("EIRH1000099", cnos)

		# Pagination.
		p1 = eir.list_my_eirs(user=me, start=0, page_length=2)
		self.assertEqual([r["container_no"] for r in p1["items"]], ["EIRH1000003", "EIRH1000002"])
		p2 = eir.list_my_eirs(user=me, start=2, page_length=2)
		self.assertEqual([r["container_no"] for r in p2["items"]], ["EIRH1000001"])
		self.assertEqual(p2["total"], 3)

		# Search by container number.
		s = eir.list_my_eirs(user=me, search="EIRH1000002")
		self.assertEqual(s["total"], 1)
		self.assertEqual(s["items"][0]["container_no"], "EIRH1000002")


class TestEirRevert(FrappeTestCase):
	"""revert_to_draft: the Desk-only 'Kembalikan ke Draft' for a submitted EIR."""

	def test_revert_eir_in_restores_container_and_makes_draft(self):
		c = _make_container("REVT1000001", status="In_Depot")
		# Empty-Clean EIR-In with no follow-up orders → tank becomes Available (an
		# Empty-Dirty EIR would instead queue a Cleaning Order; covered elsewhere).
		res = eir.create_eir(inspection_type="EIR-In", container=c, tank_status="Empty Clean", submit=True)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")

		eir.revert_to_draft(res["name"])

		doc = frappe.get_doc("Inspection", res["name"])
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual(doc.status, "Draft")
		# Container status undone back to its pre-submit value.
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")

	def test_reverted_eir_is_reopened_by_open_draft(self):
		c = _make_container("REVT1000002", status="In_Depot")
		res = eir.create_eir(inspection_type="EIR-In", container=c, submit=True)
		eir.revert_to_draft(res["name"])
		# The PWA's get-or-create draft must return THE reverted EIR, not a new one.
		opened = eir.open_draft(container=c)
		self.assertEqual(opened["inspection"], res["name"])

	def test_revert_blocked_when_another_draft_exists(self):
		c = _make_container("REVT1000003", status="In_Depot")
		submitted = eir.create_eir(inspection_type="EIR-In", container=c, submit=True)
		# A second, still-draft EIR for the same container.
		eir.create_eir(inspection_type="EIR-Out", container=c, submit=False)
		with self.assertRaises(frappe.ValidationError):
			eir.revert_to_draft(submitted["name"])
		# Untouched: the submitted EIR stays submitted.
		self.assertEqual(frappe.get_doc("Inspection", submitted["name"]).docstatus, 1)

	def test_revert_rejects_non_submitted(self):
		c = _make_container("REVT1000004")
		draft = eir.create_eir(inspection_type="EIR-In", container=c, submit=False)
		with self.assertRaises(frappe.ValidationError):
			eir.revert_to_draft(draft["name"])
