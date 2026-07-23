"""The Admin-Ops gate between the workshop's estimate and the customer web.

The workshop no longer publishes straight to the owner: ``submit_for_approval`` hands
the estimate to Admin Ops (``Service Setup``), and only ``publish_to_owner`` moves it
to ``Pending Approval`` — the first status the customer can see. Admin Ops can pull it
back (``withdraw_from_owner``) and publish again.

``requested_on`` is the tell for whether the owner has actually been asked: it is
stamped at publish, not at the workshop's submit, and cleared on withdraw.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations import mr
from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "MR Gate Test Co"
CONTAINER = "MRGT1112220"


def _cleanup():
	orders = frappe.get_all("Repair Order", filters={"container": CONTAINER}, pluck="name")
	if orders:
		frappe.db.delete("Notification Log", {"document_type": "Repair Order", "document_name": ("in", orders)})
		for child in ("Repair Damage Entry", "Repair Used Item", "Repair Cost Total"):
			frappe.db.delete(child, {"parent": ("in", orders)})
		frappe.db.delete("Repair Order", {"name": ("in", orders)})
	for log in ("Container Movement", "Container Activity"):
		frappe.db.delete(log, {"container": CONTAINER})
	if frappe.db.exists("Container", CONTAINER):
		frappe.db.delete("Container", {"name": CONTAINER})
	if frappe.db.exists("Customer", CUSTOMER):
		frappe.db.delete("Customer", {"name": CUSTOMER})
	frappe.db.commit()


class TestMrCustomerGate(FrappeTestCase):
	def setUp(self):
		# Purge before creating: _cleanup removes the Customer this test builds on.
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)
		frappe.get_doc({
			"doctype": "Container",
			"container_no": CONTAINER,
			"container_type": "ISO Tank",
			"status": "In_Depot",
			"principal": self.customer,
		}).insert(ignore_permissions=True)

	def tearDown(self):
		_cleanup()

	def _draft(self, with_items=True):
		doc = {
			"doctype": "Repair Order",
			"container": CONTAINER,
			"status": "Draft",
			"billing_status": "Unbilled",
		}
		if with_items:
			doc["used_items"] = [{"item": "Lift Off", "quantity": 1, "item_rate": 100000}]
		return frappe.get_doc(doc).insert(ignore_permissions=True)

	def _status(self, name):
		return frappe.db.get_value("Repair Order", name, ["status", "requested_on"], as_dict=True)

	def test_workshop_submit_stops_at_admin_ops(self):
		"""The whole point: the customer must not see it yet."""
		ro = self._draft()
		mr.submit_for_approval(ro.name)

		row = self._status(ro.name)
		self.assertEqual(row.status, "Service Setup")
		self.assertNotIn(row.status, mr.MR_CUSTOMER_VISIBLE_STATUSES)
		# The owner clock only starts when they are actually asked.
		self.assertIsNone(row.requested_on)

	def test_publish_puts_it_on_the_customer_web(self):
		ro = self._draft()
		mr.submit_for_approval(ro.name)
		mr.publish_to_owner(ro.name)

		row = self._status(ro.name)
		self.assertEqual(row.status, "Pending Approval")
		self.assertIn(row.status, mr.MR_CUSTOMER_VISIBLE_STATUSES)
		self.assertIsNotNone(row.requested_on)

	def test_withdraw_then_republish(self):
		"""Tarik ulang + ajukan ulang — the round trip Admin Ops needs."""
		ro = self._draft()
		mr.submit_for_approval(ro.name)
		mr.publish_to_owner(ro.name)

		mr.withdraw_from_owner(ro.name, note="harga salah")
		row = self._status(ro.name)
		self.assertEqual(row.status, "Service Setup")
		# Cleared, so the re-publish starts a fresh owner round rather than back-dating it.
		self.assertIsNone(row.requested_on)

		mr.publish_to_owner(ro.name)
		self.assertEqual(self._status(ro.name).status, "Pending Approval")

	def test_withdraw_resets_line_decisions(self):
		ro = self._draft()
		mr.submit_for_approval(ro.name)
		mr.publish_to_owner(ro.name)
		frappe.db.set_value("Repair Used Item", {"parent": ro.name}, "decision", "Approved", update_modified=False)

		mr.withdraw_from_owner(ro.name)
		decisions = frappe.get_all("Repair Used Item", filters={"parent": ro.name}, pluck="decision")
		self.assertEqual(set(decisions), {"Pending"})

	def test_withdraw_refused_once_the_owner_decided(self):
		"""A withdrawal must never erase an answer the customer already gave."""
		ro = self._draft()
		mr.submit_for_approval(ro.name)
		mr.publish_to_owner(ro.name)
		mr.record_decision(ro.name, "Approved")

		with self.assertRaises(frappe.ValidationError):
			mr.withdraw_from_owner(ro.name)
		self.assertEqual(self._status(ro.name).status, "Approved")

	def test_publish_refused_from_a_draft(self):
		"""Publishing skips the Admin-Ops step it exists to enforce, so it is refused."""
		ro = self._draft()
		with self.assertRaises(frappe.ValidationError):
			mr.publish_to_owner(ro.name)

	def test_submit_needs_at_least_one_item(self):
		ro = self._draft(with_items=False)
		with self.assertRaises(frappe.ValidationError):
			mr.submit_for_approval(ro.name)

	def test_estimate_stays_editable_in_service_setup(self):
		"""Admin Ops has to be able to arrange it — that is what the step is for."""
		self.assertIn("Service Setup", mr.MR_EDITABLE_STATUSES)
