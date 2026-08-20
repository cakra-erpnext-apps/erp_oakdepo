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
