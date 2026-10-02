"""Leak Check is finished by Submit (2026-10-02), from the Desk like every other order and from
the PWA — a photo saved on a draft no longer completes it.

Self-cleaning: every row created here is hard-deleted in tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.doctype.leak_check.leak_check import (
	has_leak_check_this_visit,
	list_leak_checks,
)
from container_depot.ess.leak_check import _record
from container_depot.tests.test_eir import _make_container

PREFIX = "LKCS"


class TestLeakCheckSubmit(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		names = frappe.get_all("Leak Check", filters={"container": ["like", f"{PREFIX}%"]}, pluck="name") or [""]
		frappe.db.delete("Notification Log", {"document_type": "Leak Check", "document_name": ["in", names]})
		frappe.db.delete("Comment", {"reference_doctype": "Leak Check", "reference_name": ["in", names]})
		frappe.db.delete("Leak Check Photo", {"parent": ["in", names]})
		frappe.db.delete("Leak Check", {"name": ["in", names]})
		for dt in ("Container Activity", "Container Movement", "Storage Charge"):
			frappe.db.delete(dt, {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})
		frappe.db.commit()
		super().tearDown()

	def _draft(self, suffix):
		c = _make_container(f"{PREFIX}{suffix}", status="Available")
		doc = frappe.get_doc({
			"doctype": "Leak Check", "container": c,
			"photos": [{"photo": "/files/leak-test.jpg", "is_leak": 1}],
		}).insert(ignore_permissions=True)
		return c, doc

	def test_a_saved_photo_leaves_it_open_and_submit_finishes_it(self):
		c, doc = self._draft("0000001")
		self.assertEqual(doc.status, "Open")
		self.assertEqual(doc.has_leak, 1)
		self.assertFalse(has_leak_check_this_visit(c))

		doc.submit()
		self.assertEqual(doc.status, "Completed")
		self.assertEqual(doc.recorded_by, "Administrator")
		self.assertTrue(doc.recorded_on)
		self.assertTrue(has_leak_check_this_visit(c))

	def test_submit_wants_a_photo(self):
		_c, doc = self._draft("0000002")
		doc.photos = []
		doc.save(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "minimal satu foto"):
			doc.submit()

	def test_a_cancelled_check_no_longer_counts_or_lists(self):
		c, doc = self._draft("0000003")
		doc.submit()
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Leak Check", doc.name, "status"), "Cancelled")
		self.assertFalse(has_leak_check_this_visit(c))
		listed = [i.name for i in list_leak_checks(search=c)["items"]]
		self.assertNotIn(doc.name, listed)

	def test_recording_from_the_pwa_submits_it(self):
		c, doc = self._draft("0000004")
		res = _record(None, [{"photo": "/files/leak-pwa.jpg"}], remarks="aman", name=doc.name)
		self.assertEqual(res["name"], doc.name)
		row = frappe.db.get_value("Leak Check", doc.name, ["docstatus", "status", "remarks"], as_dict=True)
		self.assertEqual((row.docstatus, row.status, row.remarks), (1, "Completed", "aman"))
		with self.assertRaisesRegex(frappe.ValidationError, "sudah selesai"):
			_record(None, [{"photo": "/files/leak-pwa.jpg"}], name=doc.name)
