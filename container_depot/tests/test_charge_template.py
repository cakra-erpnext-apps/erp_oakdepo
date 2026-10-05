"""Ambil Charges / Charge Template: lines copied between M&R, Cleaning and templates, priced
from the source or from the tank owner's contract, and a short part that lands on a draft
but cannot move the order on.

Container Booking is its own family (Booking Charge Template, ``CHGB`` fixtures): it never
mixes with Service & Parts, and Tank In / Tank Out keep their own lines.

Fixtures use the ``CHGT`` / ``CHGB`` prefix and are removed in tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import mr
from container_depot.container_depot.doctype.charge_template.charge_template import (
	charge_source_query,
	get_charges,
	save_as_template,
)
from container_depot.tests.test_eir import _make_container
from container_depot.tests.test_pricing_model import _contract, _drop_contracts, _ensure_item

def _drop_fixtures(customers, items):
	"""Contracts (with the bells they rang), customers and items — the items' child rows
	too, which a raw ``frappe.db.delete`` of the Item would leave behind."""
	contracts = frappe.get_all("Depot Contract", filters={"customer": ("in", customers)}, pluck="name")
	if contracts:
		frappe.db.delete("Notification Log", {"document_type": "Depot Contract", "document_name": ("in", contracts)})
	_drop_contracts(customers)
	frappe.db.delete("Customer", {"name": ("in", customers)})
	for child in ("Item Default", "UOM Conversion Detail", "Item Price"):
		frappe.db.delete(child, {"parent" if child != "Item Price" else "item_code": ("in", items)})
	frappe.db.delete("Item", {"name": ("in", items)})


_OWNER = "CHGT Owner"
_PRICED, _UNPRICED, _PART = "CHGT-WASH", "CHGT-SEAL", "CHGT-PART"
_TEMPLATES = ("CHGT Standar", "CHGT From Order")


class TestChargeTemplate(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_ensure_item(_PRICED)
		_ensure_item(_UNPRICED)
		if not frappe.db.exists("Item", _PART):
			frappe.get_doc({
				"doctype": "Item", "item_code": _PART, "item_name": _PART, "stock_uom": "Nos",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"is_stock_item": 1, "is_sales_item": 1,
			}).insert(ignore_permissions=True)
		_contract(_OWNER, [{"item": _PRICED, "rate": 36, "manhour_rate": 4, "currency": "USD"}])
		self.container = _make_container("CHGT0000001", principal=_OWNER)
		self.template = frappe.get_doc({
			"doctype": "Charge Template", "template_name": _TEMPLATES[0],
			"items": [
				{"item": _PRICED, "quantity": 2, "rate": 10, "manhour_rate": 1, "currency": "IDR", "remark": "a"},
				{"item": _UNPRICED, "quantity": 1, "rate": 5, "currency": "IDR"},
			],
		}).insert(ignore_permissions=True)
		# Any leaf warehouse will do: the part is new, so it has no stock anywhere. Borrowed,
		# not created — a created one leaves a Deleted Document behind on every test.
		self.company = mr._resolve_company()
		self.wh = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0})

	def tearDown(self):
		frappe.set_user("Administrator")
		for ro in frappe.get_all("Repair Order", filters={"container": self.container}, pluck="name"):
			for child in ("Repair Used Item", "Repair Cost Total"):
				frappe.db.delete(child, {"parent": ro})
			frappe.db.delete("Repair Order", {"name": ro})
		for co in frappe.get_all("Cleaning Order", filters={"container": self.container}, pluck="name"):
			frappe.db.delete("Cleaning Order Service", {"parent": co})
			frappe.db.delete("Cleaning Order", {"name": co})
		for dt in ("Container Activity", "Container Movement"):
			frappe.db.delete(dt, {"container": self.container})
		frappe.db.delete("Container", {"name": self.container})
		frappe.db.delete("Charge Template Item", {"parent": ("in", _TEMPLATES)})
		frappe.db.delete("Charge Template", {"name": ("in", _TEMPLATES)})
		_drop_fixtures([_OWNER], [_PRICED, _UNPRICED, _PART])
		frappe.db.commit()

	def test_rows_map_to_each_target_with_source_prices(self):
		repair = get_charges("Charge Template", self.template.name, "Repair Order")["rows"]
		self.assertEqual(
			[(r["item"], r["quantity"], r["item_rate"], r["manhour_rate"], r["remark"]) for r in repair],
			[(_PRICED, 2, 10, 1, "a"), (_UNPRICED, 1, 5, 0, None)],
		)
		cleaning = get_charges("Charge Template", self.template.name, "Cleaning Order")["rows"]
		self.assertEqual([(r["cleaning_item"], r["rate"]) for r in cleaning], [(_PRICED, 10), (_UNPRICED, 5)])

	def test_contract_price_overrides_only_what_the_contract_prices(self):
		res = get_charges("Charge Template", self.template.name, "Cleaning Order", self.container, "contract")
		self.assertTrue(res["contract"])
		priced, unpriced = res["rows"]
		self.assertEqual((priced["rate"], priced["manhour_rate"], priced["currency"]), (36, 4, "USD"))
		self.assertEqual((unpriced["rate"], unpriced["currency"]), (5, "IDR"))

	def test_order_saves_as_template_and_copies_back(self):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": self.container,
			"cleaning_services": get_charges("Charge Template", self.template.name, "Cleaning Order")["rows"],
		}).insert(ignore_permissions=True)
		self.assertEqual([r.rate for r in co.cleaning_services], [10, 5])  # copied price is kept
		name = save_as_template("Cleaning Order", co.name, _TEMPLATES[1])
		rows = frappe.get_doc("Charge Template", name).items
		self.assertEqual([(r.item, r.quantity, r.rate) for r in rows], [(_PRICED, 2, 10), (_UNPRICED, 1, 5)])

	def test_short_part_lands_on_setup_but_cannot_be_forwarded(self):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": self.container,
			"cleaning_services": [{"cleaning_item": _PART, "quantity": 1, "warehouse": self.wh}],
		}).insert(ignore_permissions=True)
		self.assertEqual(co.status, "Service Setup")
		co.status = "Pending"
		with self.assertRaises(frappe.ValidationError):
			co.save(ignore_permissions=True)

	def test_short_part_lands_on_mr_draft_but_cannot_be_forwarded(self):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": self.container,
			"used_items": [{"line_type": "Part", "item": _PART, "quantity": 1, "warehouse": self.wh}],
		}).insert(ignore_permissions=True)
		self.assertEqual(ro.status, "Draft")
		with self.assertRaises(frappe.ValidationError):
			mr.forward_to_team(ro.name)
		self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "status"), "Draft")


_BILL_TO, _OTHER = "CHGB Customer", "CHGB Other"
_LIFT, _FEE = "CHGB-LIFT", "CHGB-FEE"
_BOOKING_TEMPLATES = ("CHGB Lift Off", "CHGB Lift On", "CHGB Copy")


class TestBookingChargeTemplate(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_ensure_item(_LIFT)
		_ensure_item(_FEE)
		_contract(_BILL_TO, [{"item": _LIFT, "rate": 50, "currency": "USD"}])
		_contract(_OTHER, [])  # a customer with no rate card
		self.tank_in = self._template(_BOOKING_TEMPLATES[0], "Tank In", _OTHER)
		self.tank_out = self._template(_BOOKING_TEMPLATES[1], "Tank Out", _BILL_TO)

	def _template(self, name, direction, customer):
		return frappe.get_doc({
			"doctype": "Booking Charge Template", "template_name": name, "direction": direction, "customer": customer,
			"items": [{"item": _LIFT}, {"item": _FEE}],
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Booking Charge Template Item", {"parent": ("in", _BOOKING_TEMPLATES)})
		frappe.db.delete("Booking Charge Template", {"name": ("in", _BOOKING_TEMPLATES)})
		_drop_fixtures([_BILL_TO, _OTHER], [_LIFT, _FEE])
		frappe.db.commit()

	def test_rates_come_from_the_bookings_bill_to_contract(self):
		# Another customer's template, copied onto a _BILL_TO booking: _BILL_TO's prices,
		# whatever price_source says; outside the contract = 0.
		res = get_charges(
			"Booking Charge Template", self.tank_in.name, "Container Booking",
			price_source="source", customer=_BILL_TO, direction="Tank In",
		)
		self.assertTrue(res["contract"])
		lift, fee = res["rows"]
		self.assertEqual((lift["item"], lift["rate"], lift["currency"], lift["currency_locked"]), (_LIFT, 50, "USD", 1))
		self.assertEqual((fee["item"], fee["rate"], fee["currency_locked"]), (_FEE, 0, 0))
		# qty follows the booking's container count; work-order columns never reach it
		self.assertFalse({"qty", "quantity", "manhour_rate", "line_type", "remark"} & set(lift))

	def test_needs_a_bill_to(self):
		with self.assertRaises(frappe.ValidationError):
			get_charges("Booking Charge Template", self.tank_in.name, "Container Booking", direction="Tank In")

	def test_families_and_directions_stay_apart(self):
		with self.assertRaises(frappe.ValidationError):
			get_charges("Booking Charge Template", self.tank_in.name, "Repair Order")
		with self.assertRaises(frappe.ValidationError):
			get_charges("Booking Charge Template", self.tank_out.name, "Container Booking", customer=_BILL_TO, direction="Tank In")

	def test_picker_narrows_by_direction_and_customer(self):
		def pick(**f):
			return [r[0] for r in charge_source_query("Booking Charge Template", "CHGB", "name", 0, 20, f)]

		self.assertEqual(pick(direction="Tank Out", customer=_BILL_TO), [self.tank_out.name])
		self.assertEqual(pick(direction="Tank Out", customer=_OTHER), [])
		self.assertEqual(pick(direction="Tank In"), [self.tank_in.name])  # no customer = every customer's
		# the booking picker runs on the same two filters, whatever bookings exist
		self.assertIsInstance(
			charge_source_query("Container Booking", "", "name", 0, 5, {"direction": "Tank In", "customer": _BILL_TO}), list
		)

	def test_saved_template_keeps_customer_and_direction(self):
		name = save_as_template("Booking Charge Template", self.tank_out.name, _BOOKING_TEMPLATES[2])
		copy = frappe.get_doc("Booking Charge Template", name)
		self.assertEqual(
			(copy.customer, copy.direction, [r.item for r in copy.items]), (_BILL_TO, "Tank Out", [_LIFT, _FEE])
		)
