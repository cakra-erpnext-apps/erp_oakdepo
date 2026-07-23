"""Shared .xlsx builders for the Desk "Download Template / Master" buttons.

xlsxwriter directly rather than ``frappe.utils.xlsxutils.make_xlsx`` because that
helper emits a plain grid — no bold header, AutoFilter or freeze pane. Used by both
Depot Contract (tariff import) and Container Booking (container import).
"""

from __future__ import annotations

import frappe


def new_sheet(sheet_name: str, headers: list, widths: list):
	"""Start an .xlsx with a styled, frozen, filterable header row.

	Returns ``(output, wb, ws, fmts)``; finish with :func:`finish_sheet`. ``fmts`` carries
	a ``header`` and a ``group`` (section-banner) format.
	"""
	import io

	import xlsxwriter

	output = io.BytesIO()
	wb = xlsxwriter.Workbook(output, {"in_memory": True})
	ws = wb.add_worksheet(sheet_name)
	fmts = {
		"header": wb.add_format({"bold": True, "bg_color": "#E8E8E8", "border": 1}),
		"group": wb.add_format({"bold": True, "bg_color": "#FFF2CC"}),
	}
	for col, title in enumerate(headers):
		ws.write(0, col, title, fmts["header"])
	for col, width in enumerate(widths):
		ws.set_column(col, col, width)
	ws.freeze_panes(1, 0)  # header stays put while scrolling
	return output, wb, ws, fmts


def finish_sheet(output, wb, ws, filename: str, last_row: int, last_col: int):
	"""Apply AutoFilter across every column, close the book and serve it as a download."""
	ws.autofilter(0, 0, max(last_row, 1), last_col)
	wb.close()
	frappe.response["type"] = "download"
	frappe.response["filename"] = filename
	frappe.response["filecontent"] = output.getvalue()
