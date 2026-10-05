"""One "Cari" box on every Desk list in the Container Depot sidebar.

Frappe's list filters are one field each, a row's containers / trucks / items sit in child
tables no quick filter reaches, and six boxes side by side still left people guessing which
one to type in. So each list below gets ONE box instead (``public/js/list_search.js`` swaps
Frappe's quick filters for it) that runs a plain ``like`` on a hidden ``search_text`` column:
counts, group-by, sort, saved filters and the Filter button all keep working natively.

``search_text`` = the document name + the fields listed in :data:`SEARCH_FIELDS`
(``table.field`` reaches into a child table). It is rebuilt on every ``on_change`` — which
Frappe runs after insert, save, submit, update-after-submit, cancel AND ``db_set`` — and
backfilled after every migrate for rows that have none yet.

ponytail: only ``frappe.db.set_value`` writes (and ``db_set`` on a child row) skip the
rebuild; such a row catches up on its next save. Clear the column and migrate to rebuild
everything after changing a field list.
"""

from __future__ import annotations

import frappe

FIELD = "search_text"

# What a person types to find a row, per list. Status / date / amount fields stay out: they
# change without a save (status automation) and the Filter button already does them well.
SEARCH_FIELDS: dict[str, list[str]] = {
	# Bookings
	"Container Booking": [
		"customer", "principal", "shipper", "surveyor", "requested_by_customer", "reff_doc",
		"do_reference", "sales_name",
		"items.container_no", "items.emkl", "items.shipper", "items.truck_plate", "items.driver", "items.ro",
	],
	"Booking Code": ["booking", "container_no"],
	"Order Bongkar": [
		"booking", "emkl", "shipper", "principal", "ex_vessel",
		"containers.container_no", "containers.truck_plate", "containers.driver", "containers.ro",
	],
	"Order Muat": [
		"booking", "ro", "emkl", "shipper", "destination", "truck_plate", "driver_name",
		"containers.container_no", "containers.booking_code",
	],
	# Pekerjaan depo
	"Inspection": [
		"container_no", "container_principal", "reff_doc", "container_booking", "emkl", "shipper",
		"truck_no", "driver", "vessel", "ex_vessel", "order_ref", "referred_voucher", "out_seals.seal_no",
	],
	"Cleaning Order": ["container_no", "container_principal", "reff_doc", "container_booking", "last_cargo", "inspection"],
	"Repair Order": ["container_no", "principal", "reff_doc", "container_booking", "inspection"],
	"Survey Order": ["booking", "principal", "surveyor", "tanks.container_no"],
	"Container Position": ["container_no", "location_note"],
	"Leak Check": ["container_no", "principal", "order_bongkar", "booking"],
	# Invoicing & pembayaran
	"Sales Invoice": ["customer", "customer_name", "po_no", "items.item_name", "items.depot_source"],
	"Payment Entry": ["party", "party_name", "reference_no", "depot_references", "references.reference_name"],
	"Pending Cash": ["pay_to", "receive_from", "pending_cash_type", "number", "connection_party", "payment_no", "detail", "remark"],
	"Pending Cash Refund": ["party", "pending_cash_no", "remark"],
	"Pending Cash Type": ["title"],
	"Storage Charge": ["container", "principal", "gate_entry", "sales_invoice"],
	# Kontrak & tarif
	"Depot Contract": ["customer"],
	"Charge Template": ["description", "items.item_name"],
	"Booking Charge Template": ["customer", "description", "items.item_name"],
	# Sparepart & stock
	"Purchase Order": ["supplier", "supplier_name", "items.item_code", "items.item_name"],
	"Purchase Receipt": ["supplier", "supplier_name", "items.item_code", "items.item_name"],
	"Supplier": ["supplier_name", "supplier_group"],
	"Stock Entry": ["stock_entry_type", "remarks", "items.item_code", "items.item_name"],
	"Stock Reconciliation": ["items.item_code", "items.item_name"],
	# Master data
	"Container": ["principal", "serial_no", "emkl", "shipper", "last_cargo", "ex_vessel"],
	"Cargo": [],
	"Customer": ["customer_name", "customer_group"],
	"Depot": ["depot_name", "branch", "city"],
	"Branch": [],
	"Item": ["item_name", "item_group"],
	"Item Group": ["parent_item_group"],
	"Warehouse": ["warehouse_name", "branch"],
	"Customer Portal User": ["customer", "user", "phone"],
	"Inspection Checklist Item": ["item_name", "printed_no", "area"],
	"Inspection Damage Code": ["description", "category"],
	"Inspection Repair Code": ["description", "category"],
	"Cleaning Checklist Item": ["item_name", "section"],
	# Audit, notifikasi & akses
	"Gate Entry": ["container_no", "booking_code", "order_ref", "truck_plate", "driver_name", "eir_reference"],
	"Container Movement": ["container", "moved_by"],
	"Container Activity": ["container", "reference_name", "principal", "summary"],
	"Depot Notification Rule": ["label"],
	"Role": [],
}


def build(doc, fields: list[str]) -> str:
	"""The name, then every listed value — child rows included — once each, in order."""
	parts = [doc.get("name")]
	for f in fields:
		table, _, child = f.partition(".")
		if child:
			parts += [row.get(child) for row in doc.get(table) or []]
		else:
			parts.append(doc.get(f))
	return " · ".join(dict.fromkeys(str(p).strip() for p in parts if p and str(p).strip()))


def refresh(doc, method=None):
	"""``doc_events["*"]["on_change"]``: keep this row's ``search_text`` in step."""
	fields = SEARCH_FIELDS.get(doc.doctype)
	# The column only exists once after_migrate has run: patches earlier in the same
	# migrate save these doctypes too.
	if fields is None or not doc.meta.has_field(FIELD):
		return
	text = build(doc, fields)
	if text != (doc.get(FIELD) or ""):
		# set_value, not db_set: db_set runs on_change again.
		frappe.db.set_value(doc.doctype, doc.name, FIELD, text, update_modified=False)
		doc.set(FIELD, text)


def after_migrate():
	"""Give every listed doctype its ``search_text`` column, then fill the empty ones."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	installed = [dt for dt in SEARCH_FIELDS if frappe.db.exists("DocType", dt)]
	create_custom_fields({
		dt: [{
			"fieldname": FIELD, "label": "Search Text", "fieldtype": "Long Text",
			"hidden": 1, "read_only": 1, "no_copy": 1, "print_hide": 1, "report_hide": 1,
			"allow_on_submit": 1,
		}]
		for dt in installed
	# The field itself is fixed and plain. Validating would re-check every OTHER field of the
	# doctype, and Order Bongkar's `booking` is deliberately hidden + mandatory.
	}, ignore_validate=True)
	for dt in installed:
		backfill(dt)


def backfill(doctype: str, chunk: int = 500):
	"""Build ``search_text`` for every row that has none, from plain queries (no get_doc:
	the audit lists run to many thousands of rows)."""
	meta = frappe.get_meta(doctype)
	fields = SEARCH_FIELDS[doctype]
	parent_fields = [f for f in fields if "." not in f and meta.has_field(f)]
	tables: dict[str, list[str]] = {}
	for f in fields:
		table, _, child = f.partition(".")
		if child and meta.has_field(table) and frappe.get_meta(meta.get_field(table).options).has_field(child):
			tables.setdefault(table, []).append(child)

	names = frappe.get_all(doctype, filters={FIELD: ["is", "not set"]}, pluck="name", order_by="name")
	for i in range(0, len(names), chunk):
		rows = {r.name: r for r in frappe.get_all(
			doctype, filters={"name": ["in", names[i:i + chunk]]}, fields=["name", *parent_fields]
		)}
		for table, child_fields in tables.items():
			for r in rows.values():
				r[table] = []
			for c in frappe.get_all(
				meta.get_field(table).options,
				filters={"parenttype": doctype, "parentfield": table, "parent": ["in", list(rows)]},
				fields=["parent", *child_fields],
				order_by="idx",
			):
				rows[c.parent][table].append(c)
		for name, r in rows.items():
			frappe.db.set_value(doctype, name, FIELD, build(r, fields), update_modified=False)
		frappe.db.commit()  # per chunk: one transaction per audit table would be huge
