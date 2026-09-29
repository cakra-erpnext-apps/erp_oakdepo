"""Fill Container Booking.search_text — the column behind the list's Cari box — for every
booking saved before it existed. Same builder as the doctype's validate."""

import frappe

from container_depot.container_depot.doctype.container_booking.container_booking import build_search_text


def execute():
	frappe.reload_doc("container_depot", "doctype", "container_booking")
	for name in frappe.get_all("Container Booking", pluck="name"):
		doc = frappe.get_doc("Container Booking", name)
		frappe.db.set_value("Container Booking", name, "search_text", build_search_text(doc), update_modified=False)
