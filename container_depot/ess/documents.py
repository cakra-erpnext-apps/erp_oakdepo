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

# Only the Cleaning Certificate has a custom print format in this app; the rest
# render with Frappe's Standard format (format omitted).
CLEANING_CERT_FORMAT = "Cleaning Certificate Format"


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

	for r in frappe.get_list(
		"Cleaning Certificate",
		filters={"container": container},
		fields=["name", "certificate_no", "clean_date"],
		order_by="creation desc",
		limit_page_length=0,
	):
		documents.append(
			{
				"category": "Sertifikat Cuci",
				"label": r.certificate_no or r.name,
				"doctype": "Cleaning Certificate",
				"name": r.name,
				"status": None,
				"date": _date(r.clean_date),
				"view_url": _view_url("Cleaning Certificate", r.name, CLEANING_CERT_FORMAT),
				"pdf_url": _pdf_url("Cleaning Certificate", r.name, CLEANING_CERT_FORMAT),
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

	for doctype, category in (("Order Bongkar", "Bon Bongkar"), ("Order Muat", "Bon Muat")):
		for r in frappe.get_list(
			doctype,
			filters={"container": container},
			fields=["name", "order_status", "creation"],
			order_by="creation desc",
			limit_page_length=0,
		):
			documents.append(
				{
					"category": category,
					"label": r.name,
					"doctype": doctype,
					"name": r.name,
					"status": r.order_status,
					"date": _date(r.creation),
					"view_url": _view_url(doctype, r.name),
					"pdf_url": _pdf_url(doctype, r.name),
				}
			)

	return {"success": True, "container": container, "documents": documents}
