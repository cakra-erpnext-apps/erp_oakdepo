"""Make browsers reload the Sales Invoice / Payment Entry / Purchase Invoice forms.

The Desk caches each doctype's meta — client script included — keyed on the DocType's
``modified``. These are ERPNext doctypes: their JSON is not ours to bump, and the new client
scripts (hooks.doctype_js) and custom fields would otherwise never reach a browser that
already cached the old form. Migrate only re-imports a DocType whose JSON is newer than the
database row, so the bump holds until ERPNext itself ships a newer JSON.
"""

import frappe
from frappe.utils import now


def execute():
	for dt in ("Sales Invoice", "Payment Entry", "Purchase Invoice", "Branch"):
		frappe.db.set_value("DocType", dt, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=dt)
