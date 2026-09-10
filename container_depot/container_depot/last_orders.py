"""The latest order of each kind, mirrored onto the Container master.

Every one of these pointers is answerable by querying the order table itself, and that
query is the source of truth — these fields are a **cache**, kept so a screen that needs
"what happened to this tank last" does not have to touch six tables to find out.

Being a cache is the whole design constraint. The one denormalised pointer this app had
before (``last_order_bongkar``) was declared on the doctype and then never written by
anything, so it sat half-filled and silently wrong for as long as it existed. What keeps
these honest is that they are **recomputed from source, never stepped forward**:

* every write, submit, cancel and delete on a source order re-reads that container's latest
  order of that kind and rewrites the pointer;
* so cancelling the newest Cleaning Order does not leave a stale pointer — the recompute
  simply lands on the one before it, with no "walk backwards" logic to get wrong;
* and a pointer can always be rebuilt from nothing (:func:`refresh_container`), which is
  what the backfill patch does and what makes a missed event recoverable.

Cancelled documents never win: a tank's "last cleaning" is the last one that actually
counted, not the one somebody voided.
"""

from __future__ import annotations

import frappe

# Container field <- the doctype that feeds it, for orders naming ONE tank directly.
_DIRECT = {
	"Cleaning Order": (("last_cleaning_order", None),),
	"Repair Order": (("last_repair_order", None),),
	# One doctype, two pointers: an EIR-In and an EIR-Out are different facts about a tank.
	"Inspection": (("last_eir_in", "EIR-In"), ("last_eir_out", "EIR-Out")),
}

# Orders that carry their tanks in a child table: doctype -> (child doctype, parentfield,
# Container field).
_VIA_ROWS = {
	"Container Booking": ("Container Booking Item", "items", "last_booking"),
	"Order Bongkar": ("Container Booking Item", "containers", "last_order_bongkar"),
	"Order Muat": ("Order Container Item", "containers", "last_order_muat"),
}

SOURCES = tuple(_DIRECT) + tuple(_VIA_ROWS)

# Beyond the pointers: three FACTS the master mirrors off the bon that last moved the tank —
# who hauled it, for which factory, and off which vessel it came. They live on the Container
# because the yard asks them of the TANK, not of a document, and they are read-only there.
#
# They used to be stamped straight through at submit and never revisited, which is exactly
# the failure this module exists to avoid: a voided bon left the master claiming a haul that
# never happened, and no later bon could correct it unless it happened to carry the same
# field. Recomputed from source here instead, so a cancel lands on the bon before it.
_PARTY_FIELDS = ("emkl", "shipper", "ex_vessel")
_BON_DOCTYPES = ("Order Bongkar", "Order Muat")

# One more fact per order kind: the Reff Doc that order carries — the customer's OWN
# document number for that job (a principal's cleaning instruction, an owner's repair
# approval). It reaches the tank master because the yard and the front desk ask it of the
# TANK ("order cuci terakhir tank ini pakai dokumen apa?") without wanting to open the order.
#
# One field per kind, never merged into a single "last reff doc": these numbers come from
# different pieces of paper from different people, and one field holding whichever arrived
# last would answer a question nobody asked. For the same reason the EIR's number is NOT
# mirrored here — it is the booking's number, already answerable from `last_booking`.
#
# Recomputed from source like everything else here, BLANK INCLUDED: the value is read off
# whatever order the pointer beside it lands on, so cancelling the newest cleaning moves
# both fields back to the one before it together.
_REFF_OF = {
	"last_cleaning_order": ("Cleaning Order", "last_cleaning_reff_doc"),
	"last_repair_order": ("Repair Order", "last_repair_reff_doc"),
}


def refresh_for_doc(doc, method=None) -> None:
	"""doc_events entry point: re-cache every tank this order touches, or has just stopped
	touching.

	The before-save set matters as much as the current one — dropping a container from a
	booking's grid must clear that tank's pointer, and only the previous version of the
	document knows it was ever there.
	"""
	if doc.doctype not in _DIRECT and doc.doctype not in _VIA_ROWS:
		return
	for container in _touched(doc):
		refresh_container(container, only=doc.doctype)


def clear_for_doc(doc, method=None) -> None:
	"""``on_trash`` entry point: recompute as if this document were already gone.

	It has to happen on the way OUT, not after. Frappe runs ``on_trash`` first, then refuses
	the delete if anything still links the document, then deletes, then fires
	``after_delete`` — so a pointer left standing until ``after_delete`` would BLOCK the
	delete it was supposed to react to ("Cannot delete, linked with Container"), and any
	Container save in between would throw on the link it can no longer resolve.
	"""
	if doc.doctype not in _DIRECT and doc.doctype not in _VIA_ROWS:
		return
	for container in _touched(doc):
		refresh_container(container, only=doc.doctype, exclude=doc.name)


def refresh_container(container: str, only: str | None = None, exclude: str | None = None) -> None:
	"""Rewrite this tank's cached pointers from the order tables.

	``only`` narrows the work to the doctype that just changed — an ordinary save should not
	re-read six tables. Left out, every pointer is rebuilt, which is what a backfill wants.
	``exclude`` skips one order by name, for the document currently being deleted.
	"""
	if not container:
		return
	updates = {}
	for doctype, targets in _DIRECT.items():
		if only and doctype != only:
			continue
		for fieldname, subtype in targets:
			updates[fieldname] = _latest_direct(doctype, container, subtype, exclude)
	for doctype, (child, parentfield, fieldname) in _VIA_ROWS.items():
		if only and doctype != only:
			continue
		updates[fieldname] = _latest_via_rows(doctype, child, parentfield, container, exclude)
	for pointer, (doctype, fieldname) in _REFF_OF.items():
		# Only when the pointer beside it was just recomputed — the two always move together.
		if pointer in updates:
			updates[fieldname] = _reff_doc_of(doctype, updates[pointer])
	if only is None or only in _BON_DOCTYPES:
		updates.update(_party_stamps(container, exclude))
	if not updates:
		return
	current = frappe.db.get_value("Container", container, list(updates), as_dict=True) or {}
	changed = {k: v for k, v in updates.items() if current.get(k) != v}
	if changed:
		# db.set_value, never doc.save(): this runs inside an unrelated document's save, and
		# re-running the Container's own validation there could throw on a state that has
		# nothing to do with the order being written. update_modified stays off so a cached
		# pointer never looks like someone edited the tank.
		frappe.db.set_value("Container", container, changed, update_modified=False)


def _latest_direct(
	doctype: str, container: str, subtype: str | None, exclude: str | None = None
) -> str | None:
	filters = {"container": container, "docstatus": ["<", 2], "status": ["!=", "Cancelled"]}
	if subtype:
		filters["inspection_type"] = subtype
	if exclude:
		filters["name"] = ["!=", exclude]
	rows = frappe.get_all(
		doctype, filters=filters, pluck="name", order_by="creation desc", limit=1
	)
	return rows[0] if rows else None


def _latest_via_rows(
	doctype: str, child: str, parentfield: str, container: str, exclude: str | None = None
) -> str | None:
	# One join instead of "read the rows, then read their parents": the row table is indexed
	# on `container`, so this is a lookup rather than a scan.
	rows = frappe.db.sql(
		"""
		select p.name
		  from `tab{child}` r
		  join `tab{parent}` p on p.name = r.parent
		 where r.container = %s and r.parenttype = %s and r.parentfield = %s
		   and p.docstatus < 2 and p.name != %s
		 order by p.creation desc
		 limit 1
		""".format(child=child, parent=doctype),
		(container, doctype, parentfield, exclude or ""),
	)
	return rows[0][0] if rows else None


def _reff_doc_of(doctype: str, order: str | None) -> str | None:
	"""The Reff Doc one order carries, or ``None`` — including when it carries none."""
	if not order:
		return None
	return frappe.db.get_value(doctype, order, "reff_doc") or None

def _party_stamps(container: str, exclude: str | None = None) -> dict:
	"""``{emkl, shipper, ex_vessel}`` from the most recent non-cancelled bon that NAMES one.

	Per field "the most recent that names one", not "the most recent bon": a bon that leaves
	EMKL blank says nothing about who hauled the tank, so blanking the master on it would
	lose the answer rather than update it. The submit-time writer this replaces applied the
	same rule (it skipped blanks); recomputing keeps it while making a cancel fall back to
	the bon before instead of leaving a voided one's stamp standing.

	SUBMITTED bons only, unlike the pointers above: a draft bon is a plan, and the master
	answers what actually happened to the tank. That was the submit-time writer's rule too.

	An Order Bongkar keeps EMKL / Shipper per ROW (one bon can carry two tanks for two
	factories) and falls back to its header; an Order Muat keeps them on the header alone.
	Only a Bongkar carries a vessel — a tank leaves on a truck.
	"""
	bons = frappe.db.sql(
		"""
		select p.creation as creation,
		       coalesce(nullif(r.emkl, ''), nullif(p.emkl, ''))       as emkl,
		       coalesce(nullif(r.shipper, ''), nullif(p.shipper, '')) as shipper,
		       nullif(p.ex_vessel, '')                                as ex_vessel
		  from `tabContainer Booking Item` r
		  join `tabOrder Bongkar` p on p.name = r.parent
		 where r.container = %(container)s and r.parenttype = 'Order Bongkar'
		   and r.parentfield = 'containers' and p.docstatus = 1 and p.name != %(exclude)s
		union all
		select p.creation, nullif(p.emkl, ''), nullif(p.shipper, ''), null
		  from `tabOrder Container Item` r
		  join `tabOrder Muat` p on p.name = r.parent
		 where r.container = %(container)s and r.parenttype = 'Order Muat'
		   and r.parentfield = 'containers' and p.docstatus = 1 and p.name != %(exclude)s
		 order by creation desc
		""",
		{"container": container, "exclude": exclude or ""},
		as_dict=True,
	)
	stamps = dict.fromkeys(_PARTY_FIELDS)
	for row in bons:
		for field in _PARTY_FIELDS:
			if stamps[field] is None and row.get(field):
				stamps[field] = row[field]
	return stamps


def _touched(doc) -> set:
	"""Every container this save added, kept, or dropped."""
	if doc.doctype in _DIRECT:
		return {doc.get("container")} - {None, ""}
	_, parentfield, _ = _VIA_ROWS[doc.doctype]
	names = {r.container for r in (doc.get(parentfield) or []) if r.get("container")}
	before = doc.get_doc_before_save() if not doc.is_new() else None
	if before:
		names |= {r.container for r in (before.get(parentfield) or []) if r.get("container")}
	return names
