"""Every Desk link the app ships must still point at something that exists.

Three JSON files hand-maintained over many refactors decide what the Desk shows:
the ``Container Depot`` workspace (the link cards), the ``Container Inventory``
workspace (the dashboard) and the ``Workspace Sidebar`` (the left nav). Deleting a
Report or DocType elsewhere in the codebase does not touch them, and Frappe renders
a dangling entry as a normal-looking link that 404s on click — the failure lands on
the user, never on the developer who removed the target.

That is what these tests close: after any removal, the link lists have to be pruned
in the same commit or the suite goes red here.

``Link Type`` values are Frappe's own (``DocType`` / ``Report`` / ``Page`` /
``Workspace``); anything else is a typo, so an unknown type fails rather than being
skipped.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

APP = "container_depot"


def _load(*path):
	return json.load(open(frappe.get_app_path(APP, *path)))


class TestWorkspaceLinksResolve(FrappeTestCase):
	def _assert_target_exists(self, link_type, link_to, where):
		self.assertIn(
			link_type, ("DocType", "Report", "Page", "Workspace"), f"{where}: unknown link_type {link_type}"
		)
		self.assertTrue(
			frappe.db.exists(link_type, link_to),
			f"{where}: {link_type} '{link_to}' does not exist (stale Desk link)",
		)

	def test_container_depot_workspace_links_resolve(self):
		ws = _load("container_depot", "workspace", "container_depot", "container_depot.json")
		for link in ws["links"]:
			if link.get("type") != "Link":
				continue  # Card Break = a section header, no target
			self._assert_target_exists(
				link["link_type"], link["link_to"], f"Container Depot workspace / {link['label']}"
			)

	def test_container_inventory_shortcuts_resolve(self):
		ws = _load("container_depot", "workspace", "container_inventory", "container_inventory.json")
		for sc in ws.get("shortcuts", []):
			self._assert_target_exists(
				sc["type"], sc["link_to"], f"Container Inventory shortcut / {sc['label']}"
			)

	def test_sidebar_links_resolve(self):
		sidebar = _load("workspace_sidebar", "container_depot.json")
		for item in sidebar["items"]:
			if item.get("type") != "Link":
				continue  # Section Break
			self._assert_target_exists(
				item["link_type"], item["link_to"], f"Sidebar / {item['label']}"
			)
