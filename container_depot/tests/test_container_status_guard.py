"""A container's status is the system's to set: a person registers a tank as Gate_Out, and a
``Booked`` tank no live Tank In booking holds is released by patch v1_17."""

import glob
import json
import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

CNO = "ZZSG0000001"


class TestContainerStatusGuard(FrappeTestCase):
	def tearDown(self):
		frappe.flags.in_test = True
		for log in ("Container Movement", "Container Activity"):
			frappe.db.delete(log, {"container": CNO})
		frappe.db.delete("Container", {"name": CNO})
		frappe.db.commit()

	def _new(self, **kw):
		principal = frappe.get_all("Customer", pluck="name", limit=1)[0]
		return frappe.get_doc({
			"doctype": "Container", "container_no": CNO, "container_type": "ISO Tank", "principal": principal, **kw,
		})

	def test_a_person_cannot_register_a_tank_as_booked(self):
		frappe.flags.in_test = False  # the guard stands aside for fixtures; act like a real save
		try:
			doc = self._new(status="Booked").insert()
		finally:
			frappe.flags.in_test = True
		self.assertEqual(doc.status, "Gate_Out")

	def test_system_code_keeps_its_status(self):
		frappe.flags.in_test = False
		try:
			doc = self._new(status="Booked").insert(ignore_permissions=True)
		finally:
			frappe.flags.in_test = True
		self.assertEqual(doc.status, "Booked")

	def test_patch_releases_a_booked_tank_no_booking_holds(self):
		from container_depot.patches.v1_17.release_orphan_booked_containers import execute

		self._new(status="Booked").insert(ignore_permissions=True)
		execute()
		self.assertEqual(frappe.db.get_value("Container", CNO, "status"), "Gate_Out")


class TestStatusFieldsNeverPrefilled(FrappeTestCase):
	def test_every_status_field_is_no_copy(self):
		"""Frappe's list "+ Add" (and ?field=value URLs, and Connections "+") copy values into
		a new doc through ``route_options`` — skipping only ``no_copy`` fields. A status left
		without it is born whatever the list was filtered on: that is how a Container came
		out "Dipesan" with no booking behind it. Every status / state field in this app's
		doctypes must carry ``no_copy``."""
		root = os.path.join(frappe.get_app_path("container_depot"), "container_depot", "doctype")
		missing = []
		for path in glob.glob(os.path.join(root, "*", "*.json")):
			meta = json.load(open(path))
			if meta.get("doctype") != "DocType" or meta.get("istable") or meta.get("issingle"):
				continue
			for f in meta.get("fields", []):
				if f.get("fieldtype") in ("Section Break", "Column Break", "Tab Break", "HTML"):
					continue
				if re.search(r"(^|_)(status|state)$", f.get("fieldname", "")) and not f.get("no_copy"):
					missing.append(f"{meta['name']}.{f['fieldname']}")
		self.assertEqual(missing, [], "status fields a list filter can prefill on a new doc")
