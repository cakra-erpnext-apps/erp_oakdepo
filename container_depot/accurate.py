"""Accurate Desktop export — turn depot Sales Invoices into an import file.

Finance re-keys every invoice into Accurate by hand today (triple entry). This
module produces a single spreadsheet in Accurate's *Faktur Penjualan* import
layout so Finance can `Impor Data | Impor Dari File` instead of retyping.

Scope (P1, deliberately minimal):
  * one row per Sales Invoice line, header fields repeated per line — the shape
    Accurate's importer expects;
  * source = **submitted** depot Sales Invoices in a period (the native ERPNext
    receivables that monthly_invoicing / consolidated_billing already raise);
  * Accurate-specific codes (item code, tax code, customer code) are left as
    PLACEHOLDERS — Accurate keys on its own master codes, not ours. Fill
    ``CODE_MAP`` / ``TAX_CODE`` below (or edit the exported file) once you have
    the real codes from a downloaded Accurate template.

Accurate's own column names are only visible after you download the template
from *Penjualan → Faktur Penjualan → Impor Data* inside Accurate. The headers
below follow the standard Accurate 5 / Accurate Online layout; rename any
element of ``COLUMNS`` to match your downloaded template exactly.

Usage (Desk / bench):
    bench --site <site> execute container_depot.accurate.export_accurate \\
        --kwargs "{'period': '2026-06'}"
Returns the private File URL of the generated .xlsx.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, flt, formatdate, get_first_day, get_last_day, getdate, today

# --- Accurate mapping knobs -------------------------------------------------
# Accurate matches on ITS OWN master codes. Until you fill these, the export
# emits our codes as-is (a placeholder) so the file is still generated and
# reviewable. Map {our value: Accurate code}.
CODE_MAP: dict[str, str] = {}          # our Item code  -> Accurate "Kode Barang"
CUSTOMER_CODE_MAP: dict[str, str] = {}  # our Customer   -> Accurate "Pelanggan"
TAX_CODE = ""                           # Accurate "Kode Pajak" for PPN, e.g. "PPN"

# Column headers, in order. Rename any of these to match the header row of the
# template you download from Accurate. Order here == column order in the file.
COLUMNS = [
	"No. Faktur",        # invoice number (header, repeated per line)
	"Tanggal Faktur",    # dd/mm/yyyy
	"Pelanggan",         # customer (Accurate code — see CUSTOMER_CODE_MAP)
	"Termin",            # payment terms
	"Mata Uang",         # currency
	"Cabang",            # branch / depot
	"Keterangan Faktur", # header remark
	"Kode Barang",       # item code (Accurate code — see CODE_MAP)
	"Nama Barang",       # item / line description
	"Kuantitas",         # qty
	"Satuan",            # uom
	"Harga Satuan",      # unit rate
	"Diskon (%)",        # line discount percent
	"Kode Pajak",        # tax code (see TAX_CODE)
	"Keterangan Detail", # line remark
]


def _period_window(period=None, from_date=None, to_date=None):
	"""Resolve the posting-date window. Explicit from/to wins; else the given
	period (YYYY-MM); else the prior month."""
	if from_date and to_date:
		return getdate(from_date), getdate(to_date)
	if period:
		anchor = getdate(period + "-01")
	else:
		anchor = add_months(get_first_day(getdate(today())), -1)
	return get_first_day(anchor), get_last_day(anchor)


def _collect_invoices(from_date, to_date, branch=None, invoices=None):
	"""Submitted depot Sales Invoices in the window (or an explicit name list)."""
	if invoices:
		names = invoices if isinstance(invoices, (list, tuple)) else [invoices]
		return [n for n in names if frappe.db.exists("Sales Invoice", n)]
	filters = {
		"docstatus": 1,
		"posting_date": ["between", [str(from_date), str(to_date)]],
	}
	if branch:
		filters["branch"] = branch
	return frappe.get_all("Sales Invoice", filters=filters, pluck="name", order_by="posting_date, name")


def _rows_for_invoice(name):
	"""One export row per Sales Invoice item line."""
	si = frappe.get_doc("Sales Invoice", name)
	has_tax = bool(getattr(si, "taxes", None))
	header = {
		"No. Faktur": si.name,
		"Tanggal Faktur": formatdate(si.posting_date, "dd/MM/yyyy"),
		"Pelanggan": CUSTOMER_CODE_MAP.get(si.customer, si.customer),
		"Termin": si.get("payment_terms_template") or "",
		"Mata Uang": si.currency,
		"Cabang": si.get("branch") or "",
		"Keterangan Faktur": (si.get("remarks") or "").strip(),
	}
	rows = []
	for it in si.items:
		row = dict(header)
		row.update({
			"Kode Barang": CODE_MAP.get(it.item_code, it.item_code),
			"Nama Barang": it.item_name or it.description or it.item_code,
			"Kuantitas": flt(it.qty),
			"Satuan": it.get("uom") or it.get("stock_uom") or "",
			"Harga Satuan": flt(it.rate),
			"Diskon (%)": flt(it.get("discount_percentage")),
			"Kode Pajak": TAX_CODE if has_tax else "",
			"Keterangan Detail": (it.description or "").strip(),
		})
		rows.append(row)
	return rows


def build_rows(period=None, from_date=None, to_date=None, branch=None, invoices=None):
	"""Return (list-of-column-headers, list-of-row-dicts) — no file I/O.

	Handy for tests and previews."""
	fd, td = _period_window(period, from_date, to_date)
	names = _collect_invoices(fd, td, branch=branch, invoices=invoices)
	rows = []
	for n in names:
		rows.extend(_rows_for_invoice(n))
	return COLUMNS, rows


@frappe.whitelist()
def export_accurate(period=None, from_date=None, to_date=None, branch=None, invoices=None):
	"""Generate the Accurate import .xlsx and return its private File URL.

	Filters to submitted Sales Invoices in the period (default: prior month), or
	pass an explicit ``invoices`` name/list. Codes stay as placeholders until
	``CODE_MAP`` / ``TAX_CODE`` are filled."""
	from frappe.utils.xlsxutils import make_xlsx

	columns, rows = build_rows(period, from_date, to_date, branch, invoices)
	matrix = [columns] + [[r.get(c, "") for c in columns] for r in rows]
	xlsx = make_xlsx(matrix, "Faktur Penjualan")

	fd, td = _period_window(period, from_date, to_date)
	fname = f"accurate_faktur_penjualan_{fd}_{td}.xlsx"
	filedoc = frappe.get_doc({
		"doctype": "File",
		"file_name": fname,
		"is_private": 1,
		"content": xlsx.getvalue(),
	}).insert(ignore_permissions=True)

	frappe.msgprint(
		f"{len(rows)} baris dari {len({r['No. Faktur'] for r in rows})} faktur diekspor.",
		title="Export Accurate",
	)
	return filedoc.file_url
