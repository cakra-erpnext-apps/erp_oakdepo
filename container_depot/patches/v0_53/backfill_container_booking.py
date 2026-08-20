"""Backfill ``container_booking`` on records that pre-date the field.

The link is new; the information it holds is not. Every EIR raised from a bon already
stores that bon, and every bon stores its Container Booking, so the parentage can be
recovered by walking the chain that was there all along:

    Cleaning Order / Repair Order -> inspection -> referred_voucher (bon) -> booking

Deliberately conservative. Rows the walk cannot resolve are left blank, not guessed from
the container's most recent booking: a tank on this data appears on as many as 52 bookings,
so a guess would file real work under a visit that never happened. Blank reads as "raised
outside a booking", which is both true and how the field is meant to be read.

Idempotent — only ever fills a blank, never rewrites a value.
"""

import frappe

# Orders that inherit the booking from their EIR, and the field naming that EIR.
# "Periodic Test Order" was here too, until v0_66 took that menu down — a doctype named
# by a historical patch has to be skipped when it is gone, not assumed.
ORDER_DOCTYPES = ("Cleaning Order", "Repair Order")


def execute():
	if not frappe.db.has_column("Inspection", "container_booking"):
		return  # doctype sync has not run yet; the next migrate picks this up

	inspections = _backfill_inspections()
	orders = {dt: _backfill_orders(dt) for dt in ORDER_DOCTYPES}
	frappe.db.commit()
	print(
		"[container_depot] backfill_container_booking: "
		f"{inspections} EIR, " + ", ".join(f"{n} {dt}" for dt, n in orders.items())
	)


def _backfill_inspections() -> int:
	"""EIR -> its bon -> the bon's booking."""
	rows = frappe.get_all(
		"Inspection",
		filters={"referred_voucher": ("is", "set"), "container_booking": ("is", "not set")},
		fields=["name", "voucher_doctype", "referred_voucher"],
		limit_page_length=0,
	)
	filled = 0
	for r in rows:
		if not r.voucher_doctype:
			continue
		booking = frappe.db.get_value(r.voucher_doctype, r.referred_voucher, "booking")
		if not booking:
			continue
		frappe.db.set_value("Inspection", r.name, "container_booking", booking, update_modified=False)
		filled += 1
	return filled


def _backfill_orders(doctype: str) -> int:
	"""Work order -> its EIR -> the booking just stamped above.

	A doctype that no longer exists (or has not been synced yet) is skipped rather than
	raising: this patch also runs on a fresh site, where the table may never appear.
	"""
	if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, "inspection"):
		return 0
	rows = frappe.get_all(
		doctype,
		filters={"inspection": ("is", "set"), "container_booking": ("is", "not set")},
		pluck="name",
		limit_page_length=0,
	)
	filled = 0
	for name in rows:
		inspection = frappe.db.get_value(doctype, name, "inspection")
		booking = frappe.db.get_value("Inspection", inspection, "container_booking")
		if not booking:
			continue
		frappe.db.set_value(doctype, name, "container_booking", booking, update_modified=False)
		filled += 1
	return filled
