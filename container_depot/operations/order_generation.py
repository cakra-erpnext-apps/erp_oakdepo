"""Atomic core for issuing a bon/voucher (Order Bongkar / Order Muat) from a
booking.

One shared entry point for BOTH the SST kiosk (``api.sst_issue_order``) and the
DMS desktop button (``api.generate_order_from_booking``), so the locking and
validation rules live in exactly one place (PRO-OPS-08: "dua entry point, satu
logika").

Rules enforced here:
- 1..3 containers per bon (``MAX_CONTAINERS_PER_ORDER``).
- every selected Booking Code must belong to ``booking``, be ``Active``, unexpired,
  and share one direction (a bon is single-direction).
- code selection + order creation + flipping codes to ``Used`` happen in a single
  transaction with the codes row-locked (``SELECT ... FOR UPDATE``) so two
  concurrent issues — or the hourly expiry job — can't double-spend a code.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

MAX_CONTAINERS_PER_ORDER = 3


def _as_code_list(value):
	if value is None:
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except json.JSONDecodeError:
			frappe.throw(_("selected_codes must be a JSON array of Booking Code names."))
	if isinstance(value, (list, tuple)):
		return [str(v).strip() for v in value if v and str(v).strip()]
	frappe.throw(_("selected_codes must be a list of Booking Code names."))


def make_order(booking, selected_codes, vehicle_data=None, sst=None):
	"""Create ONE Order (Bongkar/Muat) holding 1..3 containers from
	``selected_codes`` and flip each used Booking Code ``Active``->``Used``,
	atomically. Returns the new order's name.

	``vehicle_data`` (optional dict): ``truck_plate``, ``driver_name``,
	``driver_phone``, ``transporter``, ``ex_vessel`` (Tank In),
	``destination`` (Tank Out), and ``cleaning_certificates`` = {code: cert}
	(Tank Out, one per container).
	"""
	codes = _as_code_list(selected_codes)
	if not (1 <= len(codes) <= MAX_CONTAINERS_PER_ORDER):
		frappe.throw(_("Select between 1 and {0} containers.").format(MAX_CONTAINERS_PER_ORDER))
	if len(set(codes)) != len(codes):
		frappe.throw(_("The same container was selected more than once."))
	if not booking or not frappe.db.exists("Isotank Booking", booking):
		frappe.throw(_("Booking {0} not found.").format(booking))

	vehicle_data = vehicle_data or {}
	certs = vehicle_data.get("cleaning_certificates") or {}

	frappe.db.savepoint("make_order")
	try:
		# Row-lock the candidate codes for the whole transaction.
		locked = frappe.db.sql(
			"""
			SELECT name, state, direction, booking, container, container_no, expires_at
			FROM `tabBooking Code`
			WHERE name IN %(codes)s
			FOR UPDATE
			""",
			{"codes": tuple(codes)},
			as_dict=True,
		)
		by_name = {r.name: r for r in locked}
		missing = [c for c in codes if c not in by_name]
		if missing:
			frappe.throw(_("Booking Code(s) not found: {0}").format(", ".join(missing)))

		directions = {by_name[c].direction for c in codes}
		if len(directions) != 1:
			frappe.throw(_("All containers on one bon must share the same direction."))
		direction = directions.pop()
		order_doctype = "Order Bongkar" if direction == "Tank In" else "Order Muat"

		for c in codes:
			r = by_name[c]
			label = r.container_no or r.name
			if r.booking != booking:
				frappe.throw(_("Container {0} is not on booking {1}.").format(label, booking))
			if r.state != "Active":
				frappe.throw(
					_("Container {0} is no longer pending (state {1}).").format(label, r.state)
				)
			if r.expires_at and get_datetime(r.expires_at) < now_datetime():
				frappe.throw(_("Container {0}'s booking code has expired.").format(label))

		customer = frappe.db.get_value("Isotank Booking", booking, "customer")
		remarks = vehicle_data.get("remarks") or {}
		order = frappe.new_doc(order_doctype)
		order.booking = booking
		order.order_status = "Issued"
		order.sst = sst
		order.gate_in_time = now_datetime()
		order.ro = vehicle_data.get("ro")
		order.shipper = vehicle_data.get("shipper") or customer
		order.angkutan = vehicle_data.get("angkutan") or vehicle_data.get("transporter")
		order.truck_plate = vehicle_data.get("truck_plate")
		order.driver_name = vehicle_data.get("driver_name")
		order.driver_phone = vehicle_data.get("driver_phone")
		if direction == "Tank In":
			order.ex_vessel = vehicle_data.get("ex_vessel")
			order.tanggal_bongkar = vehicle_data.get("tanggal_bongkar") or vehicle_data.get("tanggal")
		else:
			order.destination = vehicle_data.get("destination")
			order.tanggal_muat = vehicle_data.get("tanggal_muat") or vehicle_data.get("tanggal")
		for c in codes:
			r = by_name[c]
			order.append(
				"containers",
				{
					"booking_code": r.name,
					"container": r.container,
					"container_no": r.container_no,
					"remarks": remarks.get(r.name),
					"cleaning_certificate": certs.get(r.name) if direction == "Tank Out" else None,
				},
			)
		# validate() re-runs the Active/direction/scoping/count checks (and per-row
		# cleaning cert for Muat) as defense in depth.
		order.insert(ignore_permissions=True)

		# Single-use: consume each code so later scans/selections are rejected.
		for c in codes:
			frappe.db.set_value("Booking Code", c, "state", "Used", update_modified=False)
	except Exception:
		frappe.db.rollback(save_point="make_order")
		raise

	return order.name
