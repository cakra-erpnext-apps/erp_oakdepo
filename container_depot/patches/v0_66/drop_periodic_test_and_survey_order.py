"""Take down the Periodic Test and Survey Order menus — doctypes, data, and every
artefact seeded around them.

Both flows were built out but never became depot practice: the periodic test is booked
as ordinary M&R work when it happens, and third-party survey charges are billed straight
on the invoice. Keeping two dead menus in the sidebar costs an operator a decision on
every screen, so they are removed rather than hidden.

What goes, and why it is listed here rather than left to ``bench migrate``:

* the five doctypes (``Periodic Test Order`` + its two child tables, ``Survey Order`` +
  its charge table) **and their tables** — migrate's orphan sweep deletes the DocType
  record once the on-disk folder is gone, which leaves ``tab…`` behind with every row in
  it (the same trap patch v0_47 documents);
* ``Container.next_pt_due`` — the periodic-test watermark. Frappe never drops a column,
  so removing the field from container.json alone would leave the data sitting there;
* the Number Cards / Dashboard Chart / Print Format / Depot Service Menus / notification
  rule seeded for them: a card or menu left behind stays offerable in its picker, which
  is how a dead feature gets put back on a dashboard (see v0_59);
* the ``Periodic Test`` rows of the Container Activity log and the reminder ToDos the
  (now deleted) ``remind_periodic_test_due`` cron opened — both would dangle.

Deliberately KEPT:

* ``Container.last_test_date`` — the tank's plate test date. The EIR fetches it, prints
  it, and the M&R / cleaning consoles show it; it is tank master data that happened to be
  stamped by the periodic test, not a field the feature owned.
* the ``Periodic Test`` option on ``OAK Monthly Invoice.category`` and the periodic-test
  service Items (``Periodic Test 2.5 Year``, the Testing Charges) — invoices already
  issued under them are accounting history, and the Items are still sellable.

Idempotent: every step is a no-op on a site that has already been through it.
"""

from __future__ import annotations

import frappe

DOCTYPES = [
	# Children first — a parent delete would otherwise trip the link check.
	"Periodic Used Item",
	"Periodic Cost Total",
	"Survey Order Charge",
	"Periodic Test Order",
	"Survey Order",
]

NUMBER_CARDS = ["Periodic Test Aktif", "Survey Order Aktif"]
CHARTS = ["Periodic Test by Status"]
PRINT_FORMATS = ["OAK Survey Order"]
SERVICE_MENUS = ["Periodic Test", "Survey"]
NOTIFICATION_RULES = ["survey_order_submitted"]


def execute():
	_drop_feed_and_activity()
	_drop_doctypes()
	_drop_container_next_pt_due()
	_drop_dashboard_artifacts()
	_drop_print_formats()
	_drop_service_menus()
	_drop_notification_rules()
	frappe.db.commit()


def _drop_feed_and_activity():
	"""Rows that point AT the doctypes — they outlive the delete and dangle."""
	for dt in DOCTYPES:
		frappe.db.delete("Notification Log", {"document_type": dt})
	if frappe.db.table_exists("Container Activity"):
		frappe.db.delete("Container Activity", {"activity_type": "Periodic Test"})
	# The reminder cron addressed its ToDos to the Container, so there is no reference
	# type to filter on — the description is what identifies them.
	frappe.db.sql(
		"""DELETE FROM `tabToDo`
		   WHERE reference_type = 'Container' AND description LIKE 'Uji periodik untuk%%'"""
	)


def _drop_doctypes():
	for dt in DOCTYPES:
		for name in frappe.get_all("Custom DocPerm", filters={"parent": dt}, pluck="name"):
			frappe.delete_doc("Custom DocPerm", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Custom Field", filters={"dt": dt}, pluck="name"):
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
		frappe.db.delete("Property Setter", {"doc_type": dt})
		if frappe.db.exists("DocType", dt):
			# force: skip the link-integrity scan — nothing references these any more.
			frappe.delete_doc("DocType", dt, force=True, ignore_permissions=True, ignore_missing=True)
		# Drop the table by name too: on a site where migrate's orphan sweep already
		# removed the DocType record, the guard above is skipped and the rows would stay.
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")


def _drop_container_next_pt_due():
	if not frappe.db.table_exists("Container"):
		return
	if "next_pt_due" in frappe.db.get_table_columns("Container"):
		frappe.db.sql_ddl("ALTER TABLE `tabContainer` DROP COLUMN `next_pt_due`")


def _drop_dashboard_artifacts():
	for card in NUMBER_CARDS:
		if not frappe.db.exists("Number Card", card):
			continue
		try:
			frappe.db.delete("Workspace Number Card", {"number_card_name": card})
			frappe.delete_doc("Number Card", card, force=True, ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"drop number card {card}")
	for chart in CHARTS:
		if not frappe.db.exists("Dashboard Chart", chart):
			continue
		try:
			frappe.db.delete("Workspace Chart", {"chart_name": chart})
			frappe.delete_doc("Dashboard Chart", chart, force=True, ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"drop dashboard chart {chart}")


def _drop_print_formats():
	for pf in PRINT_FORMATS:
		if frappe.db.exists("Print Format", pf):
			frappe.delete_doc("Print Format", pf, force=True, ignore_permissions=True)


def _drop_service_menus():
	"""The item-picker menus that existed only to scope these two forms' pickers."""
	if not frappe.db.table_exists("Depot Service Menu"):
		return
	for menu in SERVICE_MENUS:
		if not frappe.db.exists("Depot Service Menu", menu):
			continue
		frappe.db.delete("Depot Service Menu Group", {"parent": menu})
		frappe.db.delete("Depot Service Menu Item", {"parent": menu})
		frappe.delete_doc("Depot Service Menu", menu, force=True, ignore_permissions=True)


def _drop_notification_rules():
	if not frappe.db.table_exists("Depot Notification Rule"):
		return
	for event_key in NOTIFICATION_RULES:
		if frappe.db.exists("Depot Notification Rule", event_key):
			frappe.db.delete("Depot Notification Role", {"parent": event_key})
			frappe.delete_doc(
				"Depot Notification Rule", event_key, force=True, ignore_permissions=True
			)
