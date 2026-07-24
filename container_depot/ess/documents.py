"""ESS PWA document access — Feature F2 (Document Access & Download).

Lists the documents produced in Desk for a tank — EIR (Inspection), Cleaning
Certificate, Repair Estimate (Repair Order), and Bon Bongkar/Muat (Order
Bongkar/Muat) — and hands the front-end a permission-checked PDF download URL
for each. No direct filesystem access: PDFs are streamed by Frappe's standard
``frappe.utils.print_format.download_pdf`` (which runs ``validate_print_permission``),
opened by the browser with the existing session cookie.
"""

from __future__ import annotations

from urllib.parse import urlencode

import frappe

from container_depot.api import _require_authenticated_user

# Only the Cleaning Order has a custom print format in this app; the rest
# render with Frappe's Standard format (format omitted).
CLEANING_ORDER_FORMAT = "Cleaning Order Format"


def _pdf_url(doctype, name, fmt=None):
	"""Direct server-rendered PDF download (needs a working wkhtmltopdf/chrome)."""
	params = {"doctype": doctype, "name": name}
	if fmt:
		params["format"] = fmt
	return "/api/method/frappe.utils.print_format.download_pdf?" + urlencode(params)


def _view_url(doctype, name, fmt=None):
	"""Browser-native print view (HTML). Works regardless of the server PDF
	generator — the user prints / saves-as-PDF from the browser. Primary action,
	since this bench's wkhtmltopdf can't resolve the site host for assets."""
	params = {"doctype": doctype, "name": name, "trigger_print": 1, "no_letterhead": 1}
	if fmt:
		params["format"] = fmt
	return "/printview?" + urlencode(params)


def _date(value):
	return str(value)[:10] if value else None


@frappe.whitelist(methods=["GET"])
def get_tank_documents(container):
	"""Return the documents linked to a tank, each with a PDF download URL.

	Every related-doc lookup goes through ``frappe.get_list`` so only records the
	user may read are listed; the PDF endpoint re-checks print permission on open.

	GET /api/method/container_depot.ess.documents.get_tank_documents
	"""
	_require_authenticated_user()
	frappe.has_permission("Container", doc=container, ptype="read", throw=True)

	documents = []

	for r in frappe.get_list(
		"Inspection",
		filters={"container": container},
		fields=["name", "inspection_id", "inspection_type", "status", "creation"],
		order_by="creation desc",
		limit_page_length=0,
	):
		documents.append(
			{
				"category": "EIR",
				"label": f"{r.inspection_type or 'EIR'} · {r.inspection_id or r.name}",
				"doctype": "Inspection",
				"name": r.name,
				"status": r.status,
				"date": _date(r.creation),
				"view_url": _view_url("Inspection", r.name),
				"pdf_url": _pdf_url("Inspection", r.name),
			}
		)

	# The finished Cleaning Order IS the cleanliness record (checklist, gas free, seals,
	# surveyor signature) and the proof Order Muat gates load-out on.
	for r in frappe.get_list(
		"Cleaning Order",
		filters={"container": container, "docstatus": 1},
		fields=["name", "order_id", "date_of_issue", "cleaning_end", "status"],
		order_by="creation desc",
		limit_page_length=0,
	):
		documents.append(
			{
				"category": "Laporan Cuci",
				"label": r.order_id or r.name,
				"doctype": "Cleaning Order",
				"name": r.name,
				"status": r.status,
				"date": _date(r.date_of_issue or r.cleaning_end),
				"view_url": _view_url("Cleaning Order", r.name, CLEANING_ORDER_FORMAT),
				"pdf_url": _pdf_url("Cleaning Order", r.name, CLEANING_ORDER_FORMAT),
			}
		)

	for r in frappe.get_list(
		"Repair Order",
		filters={"container": container},
		fields=["name", "status", "creation"],
		order_by="creation desc",
		limit_page_length=0,
	):
		documents.append(
			{
				"category": "Estimasi Perbaikan",
				"label": r.name,
				"doctype": "Repair Order",
				"name": r.name,
				"status": r.status,
				"date": _date(r.creation),
				"view_url": _view_url("Repair Order", r.name),
				"pdf_url": _pdf_url("Repair Order", r.name),
			}
		)

	# Order Bongkar reuses the booking's Container Booking Item child; Order Muat still
	# carries its own Order Container Item rows.
	for doctype, category, child in (
		("Order Bongkar", "Bon Bongkar", "Container Booking Item"),
		("Order Muat", "Bon Muat", "Order Container Item"),
	):
		# Find the bons that include this container, then load each parent once.
		parents = frappe.get_all(
			child,
			filters={"container": container, "parenttype": doctype},
			pluck="parent",
		)
		for name in dict.fromkeys(parents):
			r = frappe.db.get_value(doctype, name, ["order_status", "creation"], as_dict=True)
			if not r:
				continue
			documents.append(
				{
					"category": category,
					"label": name,
					"doctype": doctype,
					"name": name,
					"status": r.order_status,
					"date": _date(r.creation),
					"view_url": _view_url(doctype, name),
					"pdf_url": _pdf_url(doctype, name),
				}
			)

	return {"success": True, "container": container, "documents": documents}
