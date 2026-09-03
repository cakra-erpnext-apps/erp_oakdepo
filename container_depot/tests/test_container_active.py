"""Container ``is_active`` — the archive flag for a tank that has left the fleet.

A tank sold, scrapped or otherwise retired must stop appearing in the pickers the depot
books from, while every record it ever carried (EIRs, orders, invoices) stays exactly where
it is — which is why it is a flag and not a delete. These tests pin the two rules that make
it safe — a tank may only be retired once the depot is done with it, and a retired tank
takes no new work — plus the pickers and importers that keep an operator from trying.

The second rule is enforced server-side on every doctype that opens work on a tank, because
the Desk picker that hides retired tanks is a convenience the PWA, the importers and every
REST caller go straight past.
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.doctype.container_booking import container_booking as cb
from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "Tank Active Co"
DEPOT = "OAK1"
PREFIX = "TACT"


def _drop_booking(name: str):
	"""Bookings refuse delete_doc (Cancel is the supported route), so a fixture goes
	straight at the rows."""
	frappe.db.delete("Booking Code", {"booking": name})
	frappe.db.delete("Container Booking Item", {"parent": name})
	frappe.db.delete("Container Booking", {"name": name})
	frappe.db.commit()


def _cleanup():
	frappe.db.delete("File", {"file_name": ("like", "tank_active_probe%")})
	names = frappe.get_all("Container", filters={"container_no": ("like", f"{PREFIX}%")}, pluck="name")
	if names:
		bookings = frappe.get_all(
			"Container Booking Item", filters={"container": ("in", names)}, pluck="parent"
		)
		for b in set(bookings):
			_drop_booking(b)
		frappe.db.delete("Cleaning Order", {"container": ("in", names)})
		frappe.db.delete("Container Movement", {"container": ("in", names)})
		frappe.db.delete("Container Activity", {"container": ("in", names)})
		frappe.db.delete("Container", {"name": ("in", names)})
	if frappe.db.exists("Customer", CUSTOMER):
		frappe.db.delete("Customer", {"name": CUSTOMER})
	frappe.db.commit()


class TestContainerActive(FrappeTestCase):
	def setUp(self):
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)

	def tearDown(self):
		frappe.response.clear()
		_cleanup()

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno, *, status="Gate_Out", **kw):
		kw.setdefault("principal", self.customer)
		kw.setdefault("depot", DEPOT)
		return frappe.get_doc({
			"doctype": "Container",
			"container_no": cno,
			"container_type": "ISO Tank",
			"status": status,
			**kw,
		}).insert(ignore_permissions=True)

	def _xlsx(self, rows):
		import xlsxwriter

		buf = io.BytesIO()
		wb = xlsxwriter.Workbook(buf, {"in_memory": True})
		ws = wb.add_worksheet()
		for r, cells in enumerate(rows):
			ws.write_row(r, 0, cells)
		wb.close()
		return frappe.get_doc({
			"doctype": "File",
			"file_name": "tank_active_probe.xlsx",
			"is_private": 1,
			"content": buf.getvalue(),
		}).insert(ignore_permissions=True).file_url

	# --- the flag itself ------------------------------------------------------
	def test_a_new_container_is_active(self):
		self.assertEqual(self._container(f"{PREFIX}0000001").is_active, 1)

	def test_a_departed_tank_can_be_retired(self):
		c = self._container(f"{PREFIX}0000002", status="Gate_Out")
		c.is_active = 0
		c.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("Container", c.name, "is_active"), 0)

	def test_a_tank_still_in_the_depot_cannot_be_retired(self):
		# Retiring it would pull it out of every picker while the depot still has to gate
		# it out.
		c = self._container(f"{PREFIX}0000003", status="Available")
		c.is_active = 0
		with self.assertRaises(frappe.ValidationError):
			c.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", c.name, "is_active"), 1)

	def test_a_tank_with_open_work_cannot_be_retired_and_the_order_is_named(self):
		c = self._container(f"{PREFIX}0000004", status="Gate_Out")
		order = frappe.get_doc({
			"doctype": "Cleaning Order",
			"container": c.name,
			"customer": self.customer,
			"status": "Pending",
		}).insert(ignore_permissions=True, ignore_mandatory=True)

		c.is_active = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			c.save(ignore_permissions=True)
		# "Not allowed" sends the operator hunting; the order number is what they can finish.
		self.assertIn(order.name, str(caught.exception))

	def test_a_tank_a_live_booking_still_names_cannot_be_retired(self):
		# A booking is not "open work" (container_open_orders only counts jobs done ON a
		# tank), so it has to be asked for separately — otherwise a retired tank could still
		# be gated in tomorrow on a booking made yesterday.
		c = self._container(f"{PREFIX}0000012", status="Gate_Out")
		booking = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"principal": self.customer,
			"do_reference": "DO-RETIRED",
			"items": [{"container": c.name, "condition": "EMPTY CLEAN"}],
		}).insert(ignore_permissions=True)
		self.addCleanup(_drop_booking, booking.name)

		c.reload()
		c.is_active = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			c.save(ignore_permissions=True)
		self.assertIn(booking.name, str(caught.exception))

	def test_a_retired_tank_stays_editable(self):
		# The guard fires on the change, not on the state — otherwise a retired tank could
		# never have its spec corrected again.
		c = self._container(f"{PREFIX}0000005", status="Gate_Out")
		c.is_active = 0
		c.save(ignore_permissions=True)

		c.serial_no = "SN-CORRECTED"
		c.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", c.name, "serial_no"), "SN-CORRECTED")

	def test_retiring_can_be_undone(self):
		c = self._container(f"{PREFIX}0000006", status="Gate_Out")
		c.is_active = 0
		c.save(ignore_permissions=True)
		c.is_active = 1
		c.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("Container", c.name, "is_active"), 1)

	# --- the importers --------------------------------------------------------
	def test_the_booking_import_skips_a_retired_tank(self):
		c = self._container(f"{PREFIX}0000007", status="Gate_Out")
		c.is_active = 0
		c.save(ignore_permissions=True)

		url = self._xlsx([["Container", "Condition"], [f"{PREFIX}0000007", "EMPTY CLEAN"]])
		res = cb.parse_container_xlsx(url, direction="Tank In", principal=self.customer)

		self.assertEqual(res["rows"], [])
		# Named, not silently dropped — and NOT re-registered under the same number.
		self.assertTrue(any(f"{PREFIX}0000007" in e for e in res["errors"]))
		self.assertEqual(res["created"], [])
		self.assertEqual(frappe.db.count("Container", {"container_no": f"{PREFIX}0000007"}), 1)

	# --- the gate on every order ---------------------------------------------
	def _retired(self, cno):
		c = self._container(cno, status="Gate_Out")
		frappe.db.set_value("Container", c.name, "is_active", 0)
		return c.name

	def test_no_order_may_be_raised_on_a_retired_tank(self):
		# One assertion per doctype that opens work on a tank: the picker hides it, but the
		# rule is what the PWA and the importers actually hit.
		tank = self._retired(f"{PREFIX}0000009")
		for doctype, extra in (
			("Cleaning Order", {"customer": self.customer}),
			("Repair Order", {}),
			("Inspection", {"inspection_type": "EIR-In"}),
			("Container Position", {}),
		):
			with self.subTest(doctype=doctype), self.assertRaises(frappe.ValidationError):
				frappe.get_doc({"doctype": doctype, "container": tank, **extra}).insert(
					ignore_permissions=True, ignore_mandatory=True
				)

	def test_a_booking_may_not_name_a_retired_tank(self):
		tank = self._retired(f"{PREFIX}0000010")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({
				"doctype": "Container Booking",
				"direction": "Tank Out",
				"customer": self.customer,
				"principal": self.customer,
				"do_reference": "DO-RETIRED",
				"items": [{"container": tank, "condition": "EMPTY CLEAN"}],
			}).insert(ignore_permissions=True)

	def test_an_order_raised_before_the_tank_retired_stays_editable(self):
		# The gate fires on the container being SET, not on every save — otherwise history
		# would freeze the moment a tank leaves the fleet.
		c = self._container(f"{PREFIX}0000011", status="Gate_Out")
		order = frappe.get_doc({
			"doctype": "Cleaning Order",
			"container": c.name,
			"customer": self.customer,
			"status": "Completed",
		}).insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.set_value("Container", c.name, "is_active", 0)

		order.reload()
		order.remarks = "koreksi catatan"
		order.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Cleaning Order", order.name, "remarks"), "koreksi catatan")

	def test_the_outbound_import_skips_a_retired_tank(self):
		"""Same refusal on the way out as on the way in — a retired tank takes no new work.

		(The lift-on half used to have an importer of its own, on Gate Out Plan; that notice
		document is gone and the booking's own Import Excel does both directions.)
		"""
		c = self._container(f"{PREFIX}0000008", status="Available")
		frappe.db.set_value("Container", c.name, "is_active", 0)

		url = self._xlsx([["Container", "Condition"], [f"{PREFIX}0000008", "EMPTY CLEAN"]])
		res = cb.parse_container_xlsx(url, direction="Tank Out", principal=self.customer)

		self.assertEqual(res["rows"], [])
		self.assertTrue(any(f"{PREFIX}0000008" in e for e in res["errors"]))
		self.assertEqual(frappe.db.count("Container", {"container_no": f"{PREFIX}0000008"}), 1)
