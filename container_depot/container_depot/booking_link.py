"""Attribute depot work to the Container Booking it was raised under.

A tank's depot visit starts with a Container Booking, which issues a bon (Order Bongkar),
whose submit auto-creates the EIR-In, whose submit raises the Cleaning Order / Repair
Order. Every hop of that chain was recorded EXCEPT the last one, so "which orders belong
to this booking?" could only be answered by walking three links backwards — and only for
the EIRs that carry a bon at all.

This module writes the answer down instead: ``container_booking`` on the Inspection and on
each order it spawns.

Two rules decide the value, and both matter:

* **Only an EIR reference confers parentage.** An order raised on its own — a walk-in
  cleaning, an ad-hoc repair, a scheduled periodic test — stands alone. There is no
  fall-back to "the container's most recent booking": on this data one tank appears on 52
  bookings, so guessing would file real work under a visit that never happened. Blank means
  "not known", which is honest and searchable; a wrong link is neither.

* **A hand-picked booking must actually cover the container.** The field is editable so an
  operator can attribute work the automation could not, but a booking that never listed
  this tank is a typo, not an intention (:func:`assert_booking_covers_container`).
"""

from __future__ import annotations

import frappe
from frappe import _

# Doctypes that carry a `container_booking` link, and where each reads it from.
BOOKING_FIELD = "container_booking"


def booking_of_voucher(voucher_doctype: str | None, voucher: str | None) -> str | None:
	"""The Container Booking behind a bon (Order Bongkar / Order Muat)."""
	if not voucher_doctype or not voucher:
		return None
	return frappe.db.get_value(voucher_doctype, voucher, "booking") or None


def booking_of_inspection(inspection: str | None) -> str | None:
	"""The Container Booking an EIR was raised under.

	Prefers the EIR's own stamped ``container_booking`` (set when the EIR was created) and
	falls back to walking its bon, so this keeps working for EIRs written before the field
	existed and for any the backfill could not reach.
	"""
	if not inspection:
		return None
	row = frappe.db.get_value(
		"Inspection",
		inspection,
		[BOOKING_FIELD, "voucher_doctype", "referred_voucher"],
		as_dict=True,
	)
	if not row:
		return None
	return row.get(BOOKING_FIELD) or booking_of_voucher(row.voucher_doctype, row.referred_voucher)


def booking_covers_container(booking: str, container: str | None) -> bool:
	"""True when ``booking`` lists ``container`` among its rows.

	Matches on the Container link, not the typed number: two depots can hold tanks whose
	numbers differ only by a transcription slip, and the link is what every other join in
	the app uses.
	"""
	if not container:
		return False
	return bool(
		frappe.db.exists(
			"Container Booking Item",
			{"parent": booking, "parenttype": "Container Booking", "container": container},
		)
	)


def assert_booking_covers_container(booking: str | None, container: str | None) -> None:
	"""Refuse a Container Booking that never listed this container.

	Only ever raised for a hand-set link — everything derived from the EIR chain came from
	the booking's own bon and passes by construction.
	"""
	if not booking or not container:
		return
	if booking_covers_container(booking, container):
		return
	container_no = frappe.db.get_value("Container", container, "container_no") or container
	frappe.throw(
		_("Container Booking {0} tidak memuat container {1}. Pilih booking yang benar, atau kosongkan kalau order ini berdiri sendiri.").format(
			frappe.bold(booking), frappe.bold(container_no)
		),
		title=_("Booking Tidak Cocok"),
	)


def apply_booking_link(doc, source_inspection_field: str = "inspection") -> None:
	"""Keep ``doc.container_booking`` correct on every save of an order.

	Fills it from the referenced EIR when blank, and validates it when the operator set it
	by hand. Never clears a value the user typed and never overwrites one — re-deriving on
	each save would fight an operator who deliberately corrected the attribution.
	"""
	if doc.get(BOOKING_FIELD):
		assert_booking_covers_container(doc.get(BOOKING_FIELD), doc.get("container"))
		return
	inspection = doc.get(source_inspection_field)
	if not inspection:
		return  # standalone order — see the module docstring; do NOT guess from the container
	doc.set(BOOKING_FIELD, booking_of_inspection(inspection))
