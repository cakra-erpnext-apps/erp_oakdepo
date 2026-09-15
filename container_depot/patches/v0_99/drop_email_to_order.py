"""Remove the email→order bridge: the `reff_email` column and everything that fed it.

The site stopped taking mail in (``v0_99.stop_email_intake``), so the bridge that turned a
Communication into a Container Booking / Cleaning Order / Repair Order has nothing left to
read. Gone with it in the same commit: ``mail_to_order.py``, ``public/js/communication.js``,
and the "Correspondence" card on the Container Depot workspace and its sidebar section.

What needs a patch is the part migrate will not do on its own:

* dropping a field from a doctype JSON leaves its column in place — MariaDB keeps the data
  until someone asks for the column to go;
* a Property Setter or Custom Field someone added on ``reff_email`` outlives the field and
  then breaks form load with "Could not find Field".

Workspace and sidebar links need nothing here: both are child tables, replaced wholesale
when migrate re-imports the JSON (their ``modified`` is bumped in the same commit).
"""

import frappe

FIELD = "reff_email"
DOCTYPES = ("Container Booking", "Cleaning Order", "Repair Order")


def execute():
	for doctype in DOCTYPES:
		frappe.db.delete("Property Setter", {"doc_type": doctype, "field_name": FIELD})
		frappe.db.delete("Custom Field", {"dt": doctype, "fieldname": FIELD})

		if frappe.db.has_column(doctype, FIELD):
			frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` DROP COLUMN `{FIELD}`")
			print(f"drop_email_to_order: dropped {doctype}.{FIELD}")

	frappe.clear_cache()
