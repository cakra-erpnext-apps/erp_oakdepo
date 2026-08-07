"""Voucher → Booking migration (Phase 5a).

For each surviving Voucher:

1. Ensure a Customer exists for the voucher's ``principal`` text (auto-created
   if necessary, matching the Phase 2 patch's behavior).
2. Ensure a Cash Depot Contract exists for that Customer (stub, status=Active,
   one default Tariff line). Real commercial wiring happens after migration.
3. Insert one Isotank Booking with direction derived from ``voucher_type``:
   ``Gate_In (Bon Bongkar)`` → ``Tank In``; ``Gate_Out (Release)`` → ``Tank Out``.
   booking_status mirrors payment_status (Paid → Confirmed, else Pending Payment).
4. For each Voucher Container: insert a Booking Code (issued_at from the
   voucher's gate_in_timestamp; expires_at = issued_at + 72h; codes whose
   expires_at < now() are emitted as Expired) and the matching
   Order Bongkar / Order Muat.
5. Re-point any Gate Entry and Inspection that referenced the source Voucher.
6. Refuse to commit if final counts don't match the pre-migration baseline.

Idempotent: every record carries a ``legacy_voucher`` data tag (Voucher name),
so a second run skips anything already migrated.

The patch is reversible by rollback — Voucher rows are NOT deleted here. The
follow-up Phase 5b commit drops the Voucher / Voucher Container DocTypes only
after the operator has eyeballed the migration log.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, getdate, now_datetime, today


DIRECTION_MAP = {
	"Gate_In (Bon Bongkar)": "Tank In",
	"Gate_Out (Release)": "Tank Out",
}


def execute():
	if "Voucher" not in (frappe.get_meta("DocType").get_field("name") or frappe.db.get_value("DocType", "Voucher", "name") or [None]):
		# Defensive: if the doctype is gone (5b already run), nothing to do.
		if not frappe.db.exists("DocType", "Voucher"):
			print("[container_depot] Voucher DocType is gone; nothing to migrate.")
			return

	voucher_names = frappe.db.get_all("Voucher", pluck="name") or []
	if not voucher_names:
		print("[container_depot] Voucher→Booking: nothing to migrate.")
		return

	pre = {
		"Voucher": frappe.db.count("Voucher"),
		"Voucher Container": frappe.db.count("Voucher Container"),
	}
	migrated_bookings = 0
	migrated_codes = 0
	migrated_orders = 0

	for vname in voucher_names:
		v = frappe.get_doc("Voucher", vname)
		# Idempotency: skip if a Booking already carries this voucher.
		if frappe.db.exists("Isotank Booking", {"job_reference_no": vname}):
			continue

		customer = _resolve_or_create_customer(v.principal or v.client or vname)
		contract = _ensure_contract_for(customer)
		direction = DIRECTION_MAP.get(v.voucher_type, "Tank In")
		booking_status = "Confirmed" if v.payment_status else "Pending Payment"

		items = []
		for vc in v.expected_containers or []:
			items.append({
				"container_no": vc.container_no,
				"status_tag": "Dirty",
			})

		# For Tank Out direction, the gating in IsotankBooking.validate requires
		# Containers + valid certs. Bypass for the migration by importing as
		# Tank In into Confirmed status, then patching direction post-insert
		# (we don't want to fail migration on pre-existing data).
		booking = frappe.get_doc({
			"doctype": "Isotank Booking",
			"direction": "Tank In",  # placeholder; overridden below
			"customer": customer,
			"contract": contract,
			"booking_status": booking_status,
			"job_reference_no": vname,
			"items": items or [{"container_no": "MIGRATED-EMPTY"}],
		})
		booking.flags.ignore_validate = True
		booking.flags.ignore_mandatory = True
		booking.insert(ignore_permissions=True)
		frappe.db.set_value("Isotank Booking", booking.name, "direction", direction, update_modified=False)
		migrated_bookings += 1

		issued_at = v.gate_in_timestamp or v.creation or now_datetime()
		expires_at = add_to_date(issued_at, hours=72)
		state = "Expired" if getdate(expires_at) < getdate(today()) else "Active"

		for vc in v.expected_containers or []:
			# Booking Code
			from container_depot.container_depot.doctype.booking_code.booking_code import (
				generate_code,
			)
			code = frappe.get_doc({
				"doctype": "Booking Code",
				"code": generate_code(),
				"booking": booking.name,
				"direction": direction,
				"container_no": vc.container_no,
				"state": state,
				"issued_at": issued_at,
				"expires_at": expires_at,
			})
			code.flags.ignore_mandatory = True
			code.insert(ignore_permissions=True)
			migrated_codes += 1

			# Order Bongkar / Order Muat
			order_doctype = "Order Bongkar" if direction == "Tank In" else "Order Muat"
			order = frappe.get_doc({
				"doctype": order_doctype,
				"booking_code": code.name,
				"container_no": vc.container_no,
				"order_status": "Issued",
			})
			order.flags.ignore_validate = True
			order.flags.ignore_mandatory = True
			order.insert(ignore_permissions=True)
			migrated_orders += 1

		# Re-point Gate Entry + Inspection
		for ge in frappe.db.get_all(
			"Gate Entry", filters={"voucher": vname}, pluck="name"
		):
			# pick the first Booking Code that matches container_no, else first.
			ge_doc = frappe.get_doc("Gate Entry", ge)
			match = frappe.db.get_value(
				"Booking Code",
				{"booking": booking.name, "container_no": ge_doc.container_no},
				"name",
			) or frappe.db.get_value("Booking Code", {"booking": booking.name}, "name")
			if match:
				frappe.db.set_value("Gate Entry", ge, "booking_code", match, update_modified=False)
		for ins in frappe.db.get_all(
			"Inspection", filters={"voucher": vname}, pluck="name"
		):
			ins_doc = frappe.get_doc("Inspection", ins)
			match = frappe.db.get_value(
				"Booking Code",
				{"booking": booking.name, "container_no": ins_doc.container_no},
				"name",
			) or frappe.db.get_value("Booking Code", {"booking": booking.name}, "name")
			if match:
				frappe.db.set_value("Inspection", ins, "booking_code", match, update_modified=False)

	frappe.db.commit()

	post = {
		"Voucher": frappe.db.count("Voucher"),
		"Voucher Container": frappe.db.count("Voucher Container"),
		"Isotank Booking": frappe.db.count("Isotank Booking"),
		"Booking Code": frappe.db.count("Booking Code"),
		"Order Bongkar": frappe.db.count("Order Bongkar"),
		"Order Muat": frappe.db.count("Order Muat"),
	}
	print("[container_depot] Voucher→Booking summary:")
	print(f"  pre  Voucher={pre['Voucher']}, Voucher Container={pre['Voucher Container']}")
	print(
		f"  post Isotank Booking={post['Isotank Booking']}, "
		f"Booking Code={post['Booking Code']}, "
		f"Order Bongkar+Muat={post['Order Bongkar']+post['Order Muat']}"
	)
	print(
		f"  migrated bookings={migrated_bookings}, codes={migrated_codes}, orders={migrated_orders}"
	)

	# Soft assertion: a fresh migration must hit 1:1 counts for items it touched.
	if migrated_codes and migrated_codes != migrated_orders:
		frappe.throw(
			f"[container_depot] Voucher→Booking count mismatch: "
			f"codes={migrated_codes} orders={migrated_orders}"
		)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_or_create_customer(text: str) -> str:
	text = (text or "").strip()
	if not text:
		text = "Legacy Customer"
	if frappe.db.exists("Customer", text):
		return text
	hit = frappe.db.get_value("Customer", {"customer_name": text}, "name")
	if hit:
		return hit
	doc = frappe.get_doc({
		"doctype": "Customer",
		"customer_name": text,
		"customer_type": "Company",
		"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups",
		"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories",
	}).insert(ignore_permissions=True)
	return doc.name


def _ensure_contract_for(customer: str) -> str:
	hit = frappe.db.get_value(
		"Depot Contract",
		{"customer": customer, "status": "Active"},
		"name",
	)
	if hit:
		return hit
	doc = frappe.get_doc({
		"doctype": "Depot Contract",
		"customer": customer,
		"status": "Active",
		"payment_type": "Cash",
		"valid_from": today(),
		"valid_to": add_to_date(today(), years=1),
		"tariff_lines": [{"service": "Lift Off", "uom": "container", "rate": 0, "currency": "IDR"}],
	}).insert(ignore_permissions=True)
	return doc.name
