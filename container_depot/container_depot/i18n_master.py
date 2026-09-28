"""Master-data strings the depot PWA shows through ``_()`` at output time.

The translation-pack generator scans every ``_("literal")`` in the code; master data is
not literal, so it asks here instead:

	bench --site <site> execute container_depot.container_depot.i18n_master.master_strings

Mirrors the fields wrapped in eir.py / mr.py / ess (checklist, damage / repair codes, tank
fittings, notification rule labels, the status values shown via ``*_label``). Item names are
deliberately left out — too many and site-specific; admins add Translation rows for those.
"""

import frappe

# (doctype, field) whose distinct stored values are shown translated.
_FIELDS = (
	("Inspection Checklist Item", "area"),
	("Inspection Checklist Item", "item_name"),
	("Inspection Damage Code", "description"),
	("Inspection Repair Code", "description"),
	("Inspection Fitting Item", "compartment"),
	("Inspection Fitting Item", "item_label"),
	("Inspection Fitting Item", "slot_label"),
	# Labels stamped onto EIR rows at write time — read back translated (view_eir), and may
	# predate a rename of the master.
	("Inspection Fitting", "compartment"),
	("Inspection Fitting", "item_label"),
	("Inspection Fitting", "slot_label"),
	("Inspection Damage Entry", "area"),
	("Repair Damage Entry", "area"),
	("Depot Notification Rule", "label"),
	("Container Activity", "from_status"),
	("Container Activity", "to_status"),
)

# Select fields whose options the PWA shows translated (activity feed, open-order status).
_SELECTS = (
	("Container Activity", "activity_type"),
	("Container", "status"),
	("Cleaning Order", "status"),
	("Repair Order", "status"),
)


def _distinct(doctype, field):
	return frappe.get_all(doctype, fields=[field], pluck=field, distinct=True, limit_page_length=0)


def master_strings() -> list[str]:
	out = set()
	for doctype, field in _FIELDS:
		out.update(_distinct(doctype, field))
	for opts in _distinct("Inspection Fitting Item", "options"):
		out.update((opts or "").split("\n"))
	# Stored components are "<printed_no>. <part>" — only the part is translated.
	for dt in ("Inspection Damage Entry", "Repair Damage Entry"):
		for c in _distinct(dt, "component"):
			out.add((c or "").partition(". ")[2] or c)
	for doctype, field in _SELECTS:
		out.update((frappe.get_meta(doctype).get_field(field).options or "").split("\n"))
	out.add("Draft")  # container_status.container_open_orders' EIR-In status
	return sorted({s.strip() for s in out if s and s.strip()})
