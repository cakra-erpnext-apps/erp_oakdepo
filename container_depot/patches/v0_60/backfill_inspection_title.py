import frappe


def execute():
	"""Fill the new ``title`` on EIRs that already exist.

	The form header now reads "<kode EIR> / <no container>", sourced from a ``title`` field
	that frappe recomputes from its template on every save. Records written before the field
	existed have it blank, and a blank title falls back to the docname (EIR-2026-01526) — so
	the container number would only appear on an EIR after someone happened to re-save it.
	One pass fixes the backlog; every later write keeps itself in step.

	Rewrites every row rather than only the blank ones: the field is read-only and composed,
	so there is no hand-typed value to protect, and an unconditional pass also repairs rows
	stamped by an earlier build of this patch.
	"""
	if not frappe.db.has_column("Inspection", "title"):
		return

	frappe.db.sql(
		"""UPDATE `tabInspection`
		   SET title = CONCAT_WS(' / ', NULLIF(inspection_id, ''), NULLIF(container_no, ''))"""
	)
