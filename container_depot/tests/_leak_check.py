"""Leak Check fixtures. Gate-out refuses a tank with no Leak Check this visit
(``gate.mark_gate_out``), so suites that drive a clean EIR-Out file one first."""

from __future__ import annotations

import frappe


def make_leak_check(container: str, *, is_leak: int = 0) -> str:
	doc = frappe.get_doc({
		"doctype": "Leak Check",
		"container": container,
		"photos": [{"photo": "/files/leak-test.jpg", "is_leak": is_leak}],
	}).insert(ignore_permissions=True)
	return doc.name


def drop_leak_checks(container_filter) -> None:
	"""``container_filter``: a name, or a Frappe filter value like ``["like", "GOTU%"]``."""
	names = frappe.get_all("Leak Check", filters={"container": container_filter}, pluck="name")
	if names:
		frappe.db.delete("Leak Check Photo", {"parent": ["in", names]})
		frappe.db.delete("Leak Check", {"name": ["in", names]})
