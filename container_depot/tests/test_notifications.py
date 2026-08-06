"""Tests for document notifications and the in-PWA notification bell endpoints.

The Depot PWA role/perm tests were dropped on 2026-08-05 with the custom role model
(see container_depot/purge_roles.py) — there is no app-specific role to assert on until
the new model is designed."""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import setup_document_notifications


class TestDocumentNotifications(FrappeTestCase):
	def test_creates_all_notifications_idempotently(self):
		setup_document_notifications()
		specs = [
			("Order Bongkar", "Submit"),
			("Order Muat", "Submit"),
			("Depot Contract", "New"),
			("Container Booking", "Submit"),
			("Inspection", "Submit"),
		]
		for doctype, event in specs:
			self.assertTrue(
				frappe.db.exists(
					"Notification", {"document_type": doctype, "event": event, "is_standard": 0}
				),
				f"missing notification for {doctype}/{event}",
			)
		# Idempotent: a second run adds nothing.
		before = frappe.db.count("Notification", {"is_standard": 0})
		setup_document_notifications()
		self.assertEqual(frappe.db.count("Notification", {"is_standard": 0}), before)


class TestPwaNotificationEndpoints(FrappeTestCase):
	def test_list_and_mark_read(self):
		from container_depot.ess import notifications

		log = frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": "Test EIR notif",
				"for_user": frappe.session.user,
				"type": "Alert",
				"read": 0,
			}
		).insert(ignore_permissions=True)

		res = notifications.list_notifications(limit=20)
		self.assertIn(log.name, [i["name"] for i in res["items"]])
		self.assertGreaterEqual(res["unread"], 1)

		notifications.mark_read(log.name)
		self.assertEqual(frappe.db.get_value("Notification Log", log.name, "read"), 1)

	def test_mark_all_read(self):
		from container_depot.ess import notifications

		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": "Another notif",
				"for_user": frappe.session.user,
				"type": "Alert",
				"read": 0,
			}
		).insert(ignore_permissions=True)

		notifications.mark_all_read()
		self.assertEqual(
			frappe.db.count("Notification Log", {"for_user": frappe.session.user, "read": 0}), 0
		)
