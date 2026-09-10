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
			frappe.db.delete("Container Booking Item", {"parent": name})
			frappe.db.delete("Order Container Item", {"parent": name})
			frappe.db.delete(doctype, {"name": name})
		for c in self._containers:
			frappe.db.delete("Container", {"name": c})
		# The EMKL / Shipper parties the bon fixtures had to mint (both are Link -> Customer).
		frappe.db.delete("Customer", {"name": ("like", f"{_PREFIX} %")})
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

	def _party(self, name):
		"""EMKL / Shipper are Link -> Customer, so the fixture has to be a real party."""
		return ensure_test_customer(f"{_PREFIX} {name}")

	def _bon(self, doctype, container, *, submitted=True, created=None, **kw):
		"""A bon naming one tank. Submitted by default — the master mirrors what actually
		happened, and only a submitted bon has."""
		child = "Container Booking Item" if doctype == "Order Bongkar" else "Order Container Item"
		row = {"container": container, "container_no": container}
		row.update(kw.pop("row", {}))
		doc = self._order(doctype, containers=[row], **kw)
		frappe.db.set_value(child, doc.containers[0].name, "parenttype", doctype, update_modified=False)
		values = {"docstatus": 1} if submitted else {}
		if created:
			values["creation"] = created
		if values:
			frappe.db.set_value(doctype, doc.name, values, update_modified=False)
		return doc

	# --- what the tank actually carries: EMKL / Shipper / Ex Vessel ------------
	def test_the_master_mirrors_the_submitted_bon(self):
		c = self._container("0101")
		self._bon("Order Bongkar", c, emkl=self._party("EMKL Satu"), shipper=self._party("Pabrik A"), ex_vessel="MV ATLANTIC")
		refresh_container(c)
		self.assertEqual(self._cached(c, "emkl"), self._party("EMKL Satu"))
		self.assertEqual(self._cached(c, "shipper"), self._party("Pabrik A"))
		self.assertEqual(self._cached(c, "ex_vessel"), "MV ATLANTIC")

	def test_a_row_answers_before_the_header(self):
		"""One bon can carry two tanks for two factories, so the row wins where it speaks."""
		c = self._container("0102")
		self._bon(
			"Order Bongkar", c, emkl=self._party("EMKL Header"), shipper=self._party("Pabrik Header"),
			row={"emkl": self._party("EMKL Baris"), "shipper": self._party("Pabrik Baris")},
		)
		refresh_container(c)
		self.assertEqual(self._cached(c, "emkl"), self._party("EMKL Baris"))
		self.assertEqual(self._cached(c, "shipper"), self._party("Pabrik Baris"))

	def test_cancelling_the_bon_falls_back_to_the_one_before(self):
		"""The regression this exists for: these three used to be stamped forward at submit
		and never revisited, so a voided bon left the master naming a haul that never
		happened — and no later bon could correct it."""
		c = self._container("0103")
		self._bon("Order Bongkar", c, emkl=self._party("EMKL Lama"), ex_vessel="MV LAMA",
				  created="2026-01-01 08:00:00")
		newer = self._bon("Order Bongkar", c, emkl=self._party("EMKL Baru"), ex_vessel="MV BARU",
						  created="2026-02-01 08:00:00")
		refresh_container(c)
		self.assertEqual(self._cached(c, "emkl"), self._party("EMKL Baru"))

		frappe.db.set_value("Order Bongkar", newer.name, "docstatus", 2, update_modified=False)
		refresh_container(c)

		self.assertEqual(self._cached(c, "emkl"), self._party("EMKL Lama"))
		self.assertEqual(self._cached(c, "ex_vessel"), "MV LAMA")

	def test_a_bon_that_names_nobody_does_not_erase_the_answer(self):
		"""A blank EMKL says nothing about who hauled the tank, so blanking the master on it
		would lose the answer rather than update it — the rule the old writer applied too."""
		c = self._container("0104")
		self._bon("Order Bongkar", c, emkl=self._party("EMKL Satu"), created="2026-01-01 08:00:00")
		self._bon("Order Muat", c, created="2026-02-01 08:00:00")  # no EMKL at all
		refresh_container(c)
		self.assertEqual(self._cached(c, "emkl"), self._party("EMKL Satu"))

	def test_a_draft_bon_does_not_stamp_the_master(self):
		"""A draft is a plan; the master answers what actually happened."""
		c = self._container("0105")
		self._bon("Order Bongkar", c, submitted=False, emkl=self._party("EMKL Rencana"))
		refresh_container(c)
		self.assertIsNone(self._cached(c, "emkl"))

	def test_the_last_bon_to_speak_wins_across_both_kinds(self):
		c = self._container("0106")
		self._bon("Order Bongkar", c, emkl=self._party("EMKL Masuk"), created="2026-01-01 08:00:00")
		self._bon("Order Muat", c, emkl=self._party("EMKL Keluar"), created="2026-03-01 08:00:00")
		refresh_container(c)
		self.assertEqual(self._cached(c, "emkl"), self._party("EMKL Keluar"))

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

	# --- the customer's own document number, per order kind ---------------------
	def test_each_orders_reff_doc_lands_in_its_own_field(self):
		"""Never merged into one "last reff doc": a principal's cleaning instruction and an
		owner's repair approval are different papers from different people."""
		c = self._container("0009")
		self._order("Cleaning Order", container=c, status="Pending", reff_doc="CLN-77")
		self._order("Repair Order", container=c, status="Draft", reff_doc="MR-88")
		self.assertEqual(self._cached(c, "last_cleaning_reff_doc"), "CLN-77")
		self.assertEqual(self._cached(c, "last_repair_reff_doc"), "MR-88")

	def test_a_newer_order_without_a_reff_doc_blanks_its_field(self):
		"""The number belongs to the LAST order, not to whichever order last had one — a
		cleaning filed with no customer document must not keep wearing the previous one's."""
		c = self._container("0010")
		self._order("Cleaning Order", container=c, status="Pending", reff_doc="CLN-77")
		self._order("Cleaning Order", container=c, status="Pending")
		self.assertIsNone(self._cached(c, "last_cleaning_reff_doc"))

	def test_cancelling_the_newest_order_restores_the_previous_reff_doc(self):
		"""Pointer and number move together, both recomputed from source."""
		c = self._container("0011")
		first = self._order("Cleaning Order", container=c, status="Pending", reff_doc="CLN-77")
		second = self._order("Cleaning Order", container=c, status="Pending", reff_doc="CLN-99")
		self.assertEqual(self._cached(c, "last_cleaning_reff_doc"), "CLN-99")

		second.status = "Cancelled"
		second.flags.ignore_validate = True
		second.save(ignore_permissions=True)
		self.assertEqual(self._cached(c, "last_cleaning_order"), first.name)
		self.assertEqual(self._cached(c, "last_cleaning_reff_doc"), "CLN-77")

	# --- rebuildable from nothing ---------------------------------------------
	def test_the_cache_can_be_rebuilt_from_source(self):
		"""What the backfill patch relies on, and what makes a missed event recoverable."""
		c = self._container("0008")
		co = self._order("Cleaning Order", container=c, status="Pending")
		frappe.db.set_value("Container", c, "last_cleaning_order", None, update_modified=False)
		self.assertIsNone(self._cached(c, "last_cleaning_order"))

		refresh_container(c)
		self.assertEqual(self._cached(c, "last_cleaning_order"), co.name)
