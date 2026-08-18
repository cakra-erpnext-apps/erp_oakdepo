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


def cargo_sheet(wb, fmts):
	"""Add a "Cargo" worksheet listing the active Cargo master, and return its row count.

	Any download carrying a Last Cargo column needs it: the operator naming what was last in
	a tank has to spell it the way the master does, and typing that free-hand is how the
	wrong cleaning item gets quoted. A template's Last Cargo dropdown points at this sheet's
	column A — a range, because Excel caps an inline validation source at 255 characters and
	the cargo master is far past that.
	"""
	cargos = frappe.get_all(
		"Cargo",
		filters={"is_active": 1},
		fields=["name", "non_stolt_class", "stolt_class"],
		order_by="name asc",
	)
	ws = wb.add_worksheet("Cargo")
	for col, title in enumerate(["Cargo", "Non-Stolt Class", "Stolt Class"]):
		ws.write(0, col, title, fmts["header"])
	ws.set_column(0, 0, 36)
	ws.set_column(1, 2, 20)
	ws.freeze_panes(1, 0)
	for i, c in enumerate(cargos, start=1):
		ws.write_row(i, 0, [c.name, c.non_stolt_class, c.stolt_class])
	ws.autofilter(0, 0, max(len(cargos), 1), 2)
	return len(cargos)
