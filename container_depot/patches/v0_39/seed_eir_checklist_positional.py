"""Switch the EIR checklist to the positional (Front/Rear/Top/…) taxonomy and record the
defect / repair codes valid per component.

Source: ``reference/Book1.xlsx`` → ``container_depot.operations.eir_checklist_data``.

What it does (idempotent):
  1. Adds the 7 damage codes the workbook needs that the original 01-29 set lacked.
  2. Upserts the 138 positional checklist items (A01-H14) with their allowed-code tables.
  3. Deactivates the old 50 system-oriented items (Frame / Shell / Cladding / …) rather than
     deleting them, so submitted EIRs keep resolving their ``checklist_item`` links. Only
     ``is_active`` rows reach the PWA, so the old taxonomy simply stops being offered.
"""

import frappe

from container_depot.operations.eir_checklist_data import CHECKLIST, NEW_DAMAGE_CODES


def execute():
	frappe.reload_doc("operations", "doctype", "inspection_checklist_damage_option")
	frappe.reload_doc("operations", "doctype", "inspection_checklist_repair_option")
	frappe.reload_doc("operations", "doctype", "inspection_checklist_item")

	_ensure_damage_codes()
	kept = _upsert_checklist()
	_deactivate_legacy(kept)


def _ensure_damage_codes() -> None:
	for code, description in NEW_DAMAGE_CODES:
		if frappe.db.exists("Inspection Damage Code", code):
			continue
		frappe.get_doc(
			{
				"doctype": "Inspection Damage Code",
				"code": code,
				"description": description,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)


def _upsert_checklist() -> set:
	"""Create/refresh every positional item. Returns the set of item codes seeded."""
	seeded = set()
	for item_code, printed_no, area, item_name, sequence, damages, primary, optional in CHECKLIST:
		doc = (
			frappe.get_doc("Inspection Checklist Item", item_code)
			if frappe.db.exists("Inspection Checklist Item", item_code)
			else frappe.new_doc("Inspection Checklist Item")
		)
		doc.item_code = item_code
		doc.printed_no = str(printed_no)
		doc.area = area
		doc.item_name = item_name
		doc.sequence = sequence
		doc.is_active = 1
		# Rebuild the code tables from the workbook — this patch is the source of truth on
		# first run; later hand-edits in Desk survive because the patch only runs once.
		doc.set("allowed_damage_codes", [])
		for code in damages:
			if frappe.db.exists("Inspection Damage Code", code):
				doc.append("allowed_damage_codes", {"damage_code": code})
		doc.set("allowed_repair_codes", [])
		for code in primary:
			if frappe.db.exists("Inspection Repair Code", code):
				doc.append("allowed_repair_codes", {"repair_code": code, "is_primary": 1})
		for code in optional:
			if code in primary:
				continue  # already listed as the primary action
			if frappe.db.exists("Inspection Repair Code", code):
				doc.append("allowed_repair_codes", {"repair_code": code, "is_primary": 0})
		doc.save(ignore_permissions=True)
		seeded.add(item_code)
	return seeded


def _deactivate_legacy(kept: set) -> None:
	"""Retire the old system-oriented items (kept for historic EIR references)."""
	legacy = [
		r.name
		for r in frappe.get_all("Inspection Checklist Item", filters={"is_active": 1}, fields=["name"])
		if r.name not in kept
	]
	for name in legacy:
		frappe.db.set_value("Inspection Checklist Item", name, "is_active", 0, update_modified=False)
	if legacy:
		print(f"[container_depot] retired {len(legacy)} legacy checklist item(s).")
	print(f"[container_depot] seeded {len(kept)} positional checklist item(s).")
