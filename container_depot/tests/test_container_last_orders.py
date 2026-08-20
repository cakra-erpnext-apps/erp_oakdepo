"""The Container master caches "the latest order of each kind" — and must never go stale.

These fields exist so a screen can answer "what happened to this tank last" without
querying six tables. That only holds if the cache tracks the order tables through every
move they can make, so the tests here are deliberately about the AWKWARD moves — cancelling
the newest order, deleting it, dropping a container off a booking's grid — not about the
happy path of creating one.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.last_orders import refresh_container
from container_depot.tests.test_api import ensure_test_customer

_PREFIX = "LASTORD"


class TestContainerLastOrders(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.customer = ensure_test_customer("Last Orders Test Co")
		self._containers = []
		self._docs = []          # (doctype, name), torn down newest first

	def tearDown(self):
		for doctype, name in reversed(self._docs):
			frappe.db.delete(doctype, {"name": name})
		for c in self._containers:
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()

	# --- factories ------------------------------------------------------------
	def _container(self, suffix):
		doc = frappe.get_doc({
			"doctype": "Container",
			"container_no": f"{_PREFIX}{suffix}",
			"container_type": "ISO Tank",
			"status": "In_Depot",
			"principal": self.customer,
		}).insert(ignore_permissions=True)
		self._containers.append(doc.name)
		return doc.name

	def _order(self, doctype, **kw):
		doc = frappe.get_doc({"doctype": doctype, **kw})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._docs.append((doctype, doc.name))
		return doc

	def _cached(self, container, field):
		return frappe.db.get_value("Container", container, field)

	# --- the newest wins ------------------------------------------------------
	def test_cleaning_pointer_follows_the_newest_order(self):
		c = self._container("0001")
		first = self._order("Cleaning Order", container=c, status="Pending")
		self.assertEqual(self._cached(c, "last_cleaning_order"), first.name)

		second = self._order("Cleaning Order", container=c, status="Pending")
		self.assertEqual(self._cached(c, "last_cleaning_order"), second.name)

	def test_repair_pointer_is_stamped(self):
		c = self._container("0002")
		ro = self._order("Repair Order", container=c, status="Draft")
		self.assertEqual(self._cached(c, "last_repair_order"), ro.name)

	def test_eir_in_and_out_are_separate_pointers(self):
		c = self._container("0003")
		ein = self._order("Inspection", container=c, inspection_type="EIR-In",
						  inspector="Administrator", status="Draft")
		eout = self._order("Inspection", container=c, inspection_type="EIR-Out",
						   inspector="Administrator", status="Draft")
		self.assertEqual(self._cached(c, "last_eir_in"), ein.name)
		self.assertEqual(self._cached(c, "last_eir_out"), eout.name)

	# --- the moves that make a cache lie --------------------------------------
	def test_cancelling_the_newest_falls_back_to_the_one_before(self):
		"""The whole reason the cache is rebuilt from source instead of stepped forward."""
		c = self._container("0004")
		first = self._order("Cleaning Order", container=c, status="Pending")
		second = self._order("Cleaning Order", container=c, status="Pending")
		self.assertEqual(self._cached(c, "last_cleaning_order"), second.name)

		second.status = "Cancelled"
		second.flags.ignore_validate = True
		second.save(ignore_permissions=True)
		self.assertEqual(self._cached(c, "last_cleaning_order"), first.name)

	def test_deleting_the_only_order_clears_the_pointer(self):
		c = self._container("0005")
		co = self._order("Cleaning Order", container=c, status="Pending")
		self.assertEqual(self._cached(c, "last_cleaning_order"), co.name)

		frappe.delete_doc("Cleaning Order", co.name, force=True, ignore_permissions=True)
		self._docs.remove(("Cleaning Order", co.name))
		self.assertIsNone(self._cached(c, "last_cleaning_order"))

	def test_dropping_a_container_off_a_booking_clears_its_pointer(self):
		"""Only the previous version of the booking knows the tank was ever on it."""
		kept = self._container("0006")
		dropped = self._container("0007")
		booking = self._order(
			"Container Booking", direction="Tank In", customer=self.customer,
			booking_status="Confirmed",
			items=[{"container": kept}, {"container": dropped}],
		)
		self.assertEqual(self._cached(kept, "last_booking"), booking.name)
		self.assertEqual(self._cached(dropped, "last_booking"), booking.name)

		booking.items = [r for r in booking.items if r.container == kept]
		booking.flags.ignore_validate = True
		booking.save(ignore_permissions=True)
		self.assertEqual(self._cached(kept, "last_booking"), booking.name)
		self.assertIsNone(self._cached(dropped, "last_booking"))

	# --- rebuildable from nothing ---------------------------------------------
	def test_the_cache_can_be_rebuilt_from_source(self):
		"""What the backfill patch relies on, and what makes a missed event recoverable."""
		c = self._container("0008")
		co = self._order("Cleaning Order", container=c, status="Pending")
		frappe.db.set_value("Container", c, "last_cleaning_order", None, update_modified=False)
		self.assertIsNone(self._cached(c, "last_cleaning_order"))

		refresh_container(c)
		self.assertEqual(self._cached(c, "last_cleaning_order"), co.name)
