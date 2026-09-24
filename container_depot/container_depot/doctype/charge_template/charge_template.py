"""Charge Template — a named set of Service & Parts lines, plus "Ambil Charges" on the Desk.

M&R, Periodic Test (both ``Repair Order``) and Cleaning Order price their work in the same
shape of line: item, Jenis, qty, currency, item rate, tarif manhour, remark. Filling one in
line by line when another order (or a saved template) already holds the same lines is the
work this module removes: :func:`get_charges` hands back another document's lines in the
target's own field names, and the form appends them. Everything stays editable on the order.

Price comes from one of two places, the user's choice per copy:
  * ``source``   — the rates exactly as they stand on the order/template copied from;
  * ``contract`` — the tank owner's active Depot Contract, line by line; an item the
    contract does not price keeps the source's rate (and no contract at all = source).

Not copied: the gudang (a Part takes the target branch's default, so a line from another
depot never points at a warehouse this one cannot issue from), and anything the order
itself decides later (owner decision, stock on hand, amounts).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ChargeTemplate(Document):
	def validate(self):
		for row in self.items:
			if row.item:
				row.line_type = "Part" if frappe.db.get_value("Item", row.item, "is_stock_item") else "Jasa"
			row.quantity = flt(row.quantity) or 1


# doctype -> (child table, item field, rate field). The three documents that hold lines.
_LINES = {
	"Repair Order": ("used_items", "item", "item_rate"),
	"Cleaning Order": ("cleaning_services", "cleaning_item", "rate"),
	"Charge Template": ("items", "item", "rate"),
}
_COMMON = ("line_type", "item_name", "quantity", "currency", "manhour_rate", "remark")


def _lines_spec(doctype):
	if doctype not in _LINES:
		frappe.throw(_("{0} tidak punya baris charge.").format(doctype))
	return _LINES[doctype]


def _neutral_rows(source) -> list[dict]:
	"""A document's lines in one shape, whatever it calls its item and rate columns."""
	table, item_field, rate_field = _lines_spec(source.doctype)
	out = []
	for row in source.get(table) or []:
		if not row.get(item_field):
			continue
		line = {f: row.get(f) for f in _COMMON}
		line.update(item=row.get(item_field), rate=flt(row.get(rate_field)))
		line["quantity"] = flt(line["quantity"]) or 1
		out.append(line)
	return out


def _to_target(line, target_doctype) -> dict:
	_table, item_field, rate_field = _lines_spec(target_doctype)
	row = {f: line.get(f) for f in _COMMON}
	row.update({item_field: line["item"], rate_field: line["rate"]})
	return row


@frappe.whitelist()
def get_charges(source_doctype, source_name, target_doctype, container=None, price_source="source"):
	"""Lines of ``source_name`` shaped for ``target_doctype``'s grid. Read-only."""
	from container_depot import pricing_model
	from container_depot.container_depot.doctype.cleaning_order.cleaning_order import contract_for_container

	_lines_spec(target_doctype)
	source = frappe.get_doc(source_doctype, source_name)
	source.check_permission("read")
	lines = _neutral_rows(source)
	if not lines:
		frappe.throw(_("{0} {1} tidak punya baris Service & Parts.").format(_(source_doctype), source_name))

	contract = contract_for_container(container) if price_source == "contract" else None
	if contract:
		principal = frappe.db.get_value("Container", container, "principal")
		fallback_currency = pricing_model.currency_for_customer(principal, contract)
		for line in lines:
			tariff = pricing_model.tariff_row(line["item"], contract)
			if tariff:
				line.update(
					rate=flt(tariff.rate),
					manhour_rate=flt(tariff.manhour_rate),
					currency=tariff.currency or fallback_currency,
				)
	return {"rows": [_to_target(line, target_doctype) for line in lines], "contract": contract}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def charge_source_query(doctype, txt, searchfield, start, page_len, filters):
	"""Picker for "Ambil Charges": orders show their number with Reff Doc, tank and status
	so the right job is recognisable; templates show their row count. Newest first."""
	_lines_spec(doctype)
	filters = filters or {}
	like = f"%{txt or ''}%"
	base = [["name", "!=", filters.get("exclude") or ""]]
	if doctype == "Charge Template":
		rows = frappe.get_list(
			doctype, filters=base + [["disabled", "=", 0]],
			or_filters=[["name", "like", like], ["description", "like", like]],
			fields=["name", "description"], order_by="modified desc",
			start=start, page_length=page_len,
		)
		counts = _row_counts(doctype, [r.name for r in rows])
		return [[r.name, _("{0} baris").format(counts.get(r.name, 0)), (r.description or "")[:80]] for r in rows]

	id_field = "repair_order_id" if doctype == "Repair Order" else "order_id"
	extra = ["job_type"] if doctype == "Repair Order" else []
	if doctype == "Repair Order" and filters.get("job_type"):
		base.append(["job_type", "=", filters["job_type"]])  # M&R and Periodic Test are two menus
	rows = frappe.get_list(
		doctype, filters=base + [["status", "!=", "Cancelled"]],
		or_filters=[["name", "like", like], [id_field, "like", like], ["reff_doc", "like", like], ["container_no", "like", like]],
		fields=["name", "reff_doc", "container_no", "status", *extra], order_by="modified desc",
		start=start, page_length=page_len,
	)
	counts = _row_counts(doctype, [r.name for r in rows])
	return [
		[
			r.name,
			_("Reff: {0}").format(r.reff_doc or "-"),
			" · ".join(filter(None, [r.container_no, _(r.get("job_type") or ""), _(r.status or "")])),
			_("{0} baris").format(counts.get(r.name, 0)),
		]
		for r in rows
	]


def _row_counts(doctype, names) -> dict:
	if not names:
		return {}
	table = _lines_spec(doctype)[0]
	child = frappe.get_meta(doctype).get_field(table).options
	return dict(
		frappe.db.sql(
			f"select parent, count(*) from `tab{child}` where parenttype = %s and parent in %s group by parent",
			(doctype, tuple(names)),
		)
	)


@frappe.whitelist()
def save_as_template(source_doctype, source_name, template_name):
	"""Save an order's lines, rates included, as a new Charge Template."""
	source = frappe.get_doc(source_doctype, source_name)
	source.check_permission("read")
	lines = _neutral_rows(source)
	if not lines:
		frappe.throw(_("Order ini belum punya baris Service & Parts."))
	doc = frappe.get_doc({
		"doctype": "Charge Template",
		"template_name": (template_name or "").strip(),
		"description": _("Dari {0}").format(source_name),
		"items": [_to_target(line, "Charge Template") for line in lines],
	}).insert()
	return doc.name
