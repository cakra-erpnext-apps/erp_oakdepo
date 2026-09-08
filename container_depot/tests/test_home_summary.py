"""Tests for the Beranda (PWA home) endpoint ``container_depot.ess.home.get_home_summary``.

The endpoint is an aggregation of counts over separately-tested worklists, so what is
tested here is what it adds on top of them:

* the response **shape** — every tile key Beranda reads is present, so a missing key
  cannot silently blank a card;
* the ``today`` counts move by the right **delta** when a fixture is added (delta rather
  than exact, because an unrestricted user counts instance-wide on a shared site);
* ``_queue`` — the "Menunggu Anda" row builder — names the container only when the queue
  holds exactly one item, which is the rule the whole section's wording depends on;
* Guest is rejected.

The ``waiting`` LIST itself is asserted only through ``_queue``: the endpoint caps it at
six rows sorted by age, so on a site with older work of its own a freshly created fixture
may legitimately fall off the end.

FrappeTestCase wraps each test in a transaction and rolls it back; ``_teardown`` clears
anything a committing controller slipped through, before and after the class.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from container_depot.ess.home import _queue, get_home_summary
from container_depot.tests.test_api import ensure_test_branch, ensure_test_customer

DEPOT = "HOMET"
PREFIX = "HOME"
PRINCIPAL = "Home Summary Test Principal"


def _teardown():
	names = frappe.get_all("Container", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name")
	if names:
		for dt in ["Container Movement", "Container Activity", "Cleaning Order", "Repair Order", "Inspection"]:
			frappe.db.delete(dt, {"container": ["in", names]})
		frappe.db.delete("Container", {"name": ["in", names]})
	if frappe.db.exists("Depot", DEPOT):
		frappe.db.delete("Depot", {"name": DEPOT})
	# The test principal too: `ensure_test_customer` commits, so it would otherwise outlive
	# the run and pile up in the customer list of a working site.
	for cust in frappe.get_all("Customer", filters={"customer_name": PRINCIPAL}, pluck="name"):
		frappe.delete_doc("Customer", cust, force=True, ignore_permissions=True, delete_permanently=True)
	frappe.db.commit()


class TestHomeSummary(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		_teardown()
		frappe.get_doc({
			"doctype": "Depot",
			"depot_code": DEPOT,
			"depot_name": "Home Summary Test Depot",
			"branch": ensure_test_branch(),
		}).insert(ignore_permissions=True)
		self.principal = ensure_test_customer(PRINCIPAL)

	def _container(self, no, status="Available"):
		frappe.get_doc({
			"doctype": "Container",
			"container_no": no,
			"container_type": "ISO Tank",
			"status": status,
			"depot": DEPOT,
			"principal": self.principal,
		}).insert(ignore_permissions=True)
		return no

	# --- shape -------------------------------------------------------------
	def test_summary_shape(self):
		res = get_home_summary()
		self.assertTrue(res["success"])
		self.assertTrue(res["menu"], "Administrator should hold every PWA menu")
		# One key per tile Beranda draws; a missing one blanks a card rather than erroring.
		for key in (
			"gate_in", "gate_out", "booking_out",
			"eir_open", "eir_review", "eir_review_age",
			"cleaning_open", "cleaning_idle",
		):
			self.assertIn(key, res["today"])
		self.assertIsInstance(res["waiting"], list)
		for row in res["waiting"]:
			self.assertEqual(set(row), {"key", "count", "ref", "age"})
			self.assertGreater(row["count"], 0)

	# --- today's tiles (delta, instance-wide) ------------------------------
	def test_gate_in_delta(self):
		c = self._container("HOME0000010")
		before = get_home_summary()["today"]
		frappe.get_doc({
			"doctype": "Container Activity",
			"container": c,
			"activity_type": "Gate In",
			"activity_time": now_datetime(),
			"depot": DEPOT,
		}).insert(ignore_permissions=True)
		after = get_home_summary()["today"]
		self.assertEqual(after["gate_in"], before["gate_in"] + 1)
		self.assertEqual(after["gate_out"], before["gate_out"])  # unrelated type untouched

	def test_cleaning_and_eir_review_deltas(self):
		c = self._container("HOME0000020")
		before = get_home_summary()["today"]

		frappe.get_doc(
			{"doctype": "Cleaning Order", "container": c, "status": "Pending"}
		).insert(ignore_permissions=True)
		insp = frappe.get_doc({
			"doctype": "Inspection",
			"container": c,
			"inspection_type": "EIR-In",
			"inspector": "Administrator",
		}).insert(ignore_permissions=True)
		# Straight to the field the endpoint filters on: "Pending Review" is reached from
		# the PWA by finishing a checklist, which is not what this test is about.
		frappe.db.set_value("Inspection", insp.name, "status", "Pending Review", update_modified=False)

		after = get_home_summary()["today"]
		self.assertEqual(after["cleaning_open"], before["cleaning_open"] + 1)
		self.assertEqual(after["cleaning_idle"], before["cleaning_idle"] + 1)
		self.assertEqual(after["eir_review"], before["eir_review"] + 1)
		# A queue with something in it always has an age; the tile prints it as "tertua 2 jam".
		self.assertIsNotNone(after["eir_review_age"])
		self.assertGreaterEqual(after["eir_review_age"], 0)
		# The EIR is awaiting review, so it is NOT in the "belum dikerjakan" count.
		self.assertEqual(after["eir_open"], before["eir_open"])

	# --- "Menunggu Anda" row builder ---------------------------------------
	def test_queue_names_the_container_only_when_alone(self):
		a = self._container("HOME0000030")
		b = self._container("HOME0000031")
		filters = {"status": ["in", ("Service Setup", "Pending")], "docstatus": ["<", 2], "depot": DEPOT}
		self.assertIsNone(_queue("cleaningIdle", "Cleaning Order", filters), "empty queue = no row")

		frappe.get_doc({"doctype": "Cleaning Order", "container": a, "status": "Pending"}).insert(
			ignore_permissions=True
		)
		row = _queue("cleaningIdle", "Cleaning Order", filters)
		self.assertEqual(row["count"], 1)
		self.assertEqual(row["ref"], a)
		self.assertIsNotNone(row["age"])

		frappe.get_doc({"doctype": "Cleaning Order", "container": b, "status": "Pending"}).insert(
			ignore_permissions=True
		)
		row = _queue("cleaningIdle", "Cleaning Order", filters)
		self.assertEqual(row["count"], 2)
		self.assertIsNone(row["ref"], "two items: the row counts, it does not pick a favourite")

	# --- auth guard --------------------------------------------------------
	def test_guest_is_rejected(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_home_summary()
		finally:
			frappe.set_user("Administrator")
