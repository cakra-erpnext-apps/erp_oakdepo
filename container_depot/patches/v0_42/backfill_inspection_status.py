import frappe


def execute():
	"""Bring every Inspection's ``status`` field in step with its lifecycle.

	The status field only started tracking the lifecycle recently: ``on_submit`` now writes
	"Submitted", ``on_cancel`` "Cancelled", and the PWA review gate "Pending Review". EIRs
	submitted / cancelled before that were left at "Draft" in the field — so a finished EIR
	reads "Draft" on the Desk form and the two surfaces disagree. This reconciles the stored
	value once; the doc events keep it correct from here on.

	Display already keyed off docstatus (inspection_list.js), so this changes the FIELD, not
	the list colour. "Pending Review" (a docstatus-0 review state) is preserved.
	"""
	if not frappe.db.table_exists("Inspection"):
		return

	# Submitted / cancelled are unambiguous from docstatus.
	frappe.db.sql("""UPDATE `tabInspection` SET `status`='Cancelled' WHERE docstatus=2 AND `status`!='Cancelled'""")
	frappe.db.sql("""UPDATE `tabInspection` SET `status`='Submitted' WHERE docstatus=1 AND `status`!='Submitted'""")
	# Drafts: anything at docstatus 0 that isn't a live review state normalises to Draft
	# (also mops up the now-removed "Completed" option, should any row carry it).
	frappe.db.sql(
		"""UPDATE `tabInspection` SET `status`='Draft'
		   WHERE docstatus=0 AND (`status` IS NULL OR `status` NOT IN ('Draft','Pending Review'))"""
	)
