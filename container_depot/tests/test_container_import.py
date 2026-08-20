"""Excel import for the Container Booking grid — parser and the two download endpoints.

These tests pin the normalisation, dedupe, default-condition and invalid-condition
branches, that the resolved link is returned when the container already exists, and the
direction-dependent handling of a number the master does not know: registered on the spot
and flagged ``is_new`` on a Tank In, skipped and reported on a Tank Out. The Tank In
half continues on the booking itself — saving claims the phantom the import created, and
cancelling deletes it.
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.doctype.container_booking import container_booking as cb
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests._booking_helpers import cancel_submitted_booking

CUSTOMER = "Cont Import Co"
EXISTING = "CIMU1112223"


def _xlsx(rows: list) -> str:
	"""Build an .xlsx in memory, store it as a File, return its file_url."""
	import xlsxwriter

	buf = io.BytesIO()
	wb = xlsxwriter.Workbook(buf, {"in_memory": True})
	ws = wb.add_worksheet()
	for r, cells in enumerate(rows):
		ws.write_row(r, 0, cells)
	wb.close()
	f = frappe.get_doc({
		"doctype": "File",
		"file_name": "container_import_probe.xlsx",
		"is_private": 1,
		"content": buf.getvalue(),
	}).insert(ignore_permissions=True)
	return f.file_url


def _drop_booking(name: str):
	"""Bookings refuse delete_doc (Cancel is the supported route), so a test fixture has to
	go straight at the rows."""
	frappe.db.delete("Booking Code", {"booking": name})
	frappe.db.delete("Container Booking Item", {"parent": name})
	frappe.db.delete("Container Booking", {"name": name})
	frappe.db.commit()


def _cleanup():
	# Frappe suffixes a duplicate file_name (…probe<hash>.xlsx), so match the prefix,
	# not the exact name, or the re-uploaded copies leak.
	frappe.db.delete("File", {"file_name": ("like", "container_import_probe%")})
	# Every probe number shares the CIMU… prefix (Container is named after its number), and
	# a Tank In booking mints a master for one that was not registered — so sweep by prefix
	# rather than by name, whether or not a test got far enough to create it.
	probes = ("like", "CIMU%")
	frappe.db.delete("Container Movement", {"container": probes})
	frappe.db.delete("Container Activity", {"container": probes})
	frappe.db.delete("Container", {"container_no": probes})
	if frappe.db.exists("Customer", CUSTOMER):
		frappe.db.delete("Customer", {"name": CUSTOMER})
	frappe.db.commit()


class TestContainerImport(FrappeTestCase):
	def setUp(self):
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)

	def tearDown(self):
		# frappe.response is process-global; a download test leaves it set.
		frappe.response.clear()
		_cleanup()

	def _tank_in(self, items):
		"""A saved Tank In booking carrying ``items`` — the shape the grid hands over."""
		booking = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"principal": self.customer,
			"do_reference": "DO-IMPORT",
			"items": items,
		}).insert(ignore_permissions=True)
		self.addCleanup(_drop_booking, booking.name)
		return booking

	def test_parse_normalises_dedupes_defaults_and_rejects(self):
		url = _xlsx([
			["Container", "Condition"],          # header, skipped
			["cimu9990001", "empty dirty"],      # lower-case -> normalised
			["CIMU9990001", "LADEN"],            # duplicate container -> collapsed (first wins)
			["cimu9990002", ""],                 # blank condition -> default EMPTY CLEAN
			["cimu9990003", "SPARKLING"],        # unknown condition -> error, skipped
		])
		res = cb.parse_container_xlsx(url, direction="Tank In", principal=self.customer)

		self.assertEqual([r["container_no"] for r in res["rows"]], ["CIMU9990001", "CIMU9990002"])
		self.assertEqual(res["rows"][0]["condition"], "EMPTY DIRTY")
		self.assertEqual(res["rows"][1]["condition"], "EMPTY CLEAN")
		self.assertEqual(len(res["errors"]), 1)
		self.assertIn("SPARKLING", res["errors"][0])

	def test_tank_in_registers_an_unknown_tank_and_flags_it(self):
		# A tank arriving for the first time HAS no master — the normal case for an inbound
		# notice — so the importer registers it rather than dropping the row. It must come
		# back with the link filled: the row's Container is mandatory, and a row without one
		# cannot be saved from the Desk at all.
		url = _xlsx([["Container", "Condition"], ["cimu9990004", "EMPTY DIRTY"]])
		res = cb.parse_container_xlsx(url, direction="Tank In", principal=self.customer)

		self.assertEqual(res["unknown"], [])
		self.assertEqual(res["created"], ["CIMU9990004"])
		self.assertEqual(res["rows"][0]["container"], "CIMU9990004")
		self.assertEqual(res["rows"][0]["is_new"], 1)
		# Registered on the Container form's own terms: Gate_Out = the master exists but the
		# tank is not in the yard. NOT Booked — that means "reserved by a Tank In booking",
		# and the booking importing it is still unsaved and has no name to reserve it.
		self.assertEqual(
			frappe.db.get_value("Container", "CIMU9990004", ["status", "principal"]),
			("Gate_Out", self.customer),
		)

	def test_tank_in_refuses_to_register_without_a_principal(self):
		# A Container cannot exist without an owner and this must not guess one.
		url = _xlsx([["Container", "Condition"], ["cimu9990009", "EMPTY CLEAN"]])
		with self.assertRaises(frappe.ValidationError):
			cb.parse_container_xlsx(url, direction="Tank In", principal=None)
		self.assertFalse(frappe.db.exists("Container", "CIMU9990009"))

	def test_tank_out_still_skips_an_unregistered_tank(self):
		# A tank that was never in the depot cannot leave it, so the number is a typo.
		url = _xlsx([["Container", "Condition"], ["cimu9990005", "EMPTY CLEAN"]])
		res = cb.parse_container_xlsx(url, direction="Tank Out")

		self.assertEqual(res["rows"], [])
		self.assertEqual(res["unknown"], ["CIMU9990005"])

	def test_parse_resolves_an_existing_container_link(self):
		frappe.get_doc({
			"doctype": "Container",
			"container_no": EXISTING,
			"container_type": "ISO Tank",
			"status": "Available",
			"principal": self.customer,
		}).insert(ignore_permissions=True)

		url = _xlsx([["Container", "Condition"], [EXISTING.lower(), "LADEN"]])
		res = cb.parse_container_xlsx(url, direction="Tank In", principal=self.customer)

		self.assertEqual(len(res["rows"]), 1)
		# The link is returned so the grid shows the container at once, not after Save.
		self.assertEqual(res["rows"][0]["container"], EXISTING)
		# ...and it is NOT badged as new — it came from the master.
		self.assertEqual(res["rows"][0]["is_new"], 0)
		self.assertEqual(res["created"], [])

	def test_saving_a_tank_in_claims_the_imported_container(self):
		# The other half of the Tank In import: the master already exists (the parse made
		# it), and Save is what stamps created_by_booking on it — which is what makes the
		# phantom cleanable, and what the row's badge is derived from.
		frappe.get_doc({
			"doctype": "Container",
			"container_no": EXISTING,
			"container_type": "ISO Tank",
			"status": "Available",
			"principal": self.customer,
		}).insert(ignore_permissions=True)
		imported = cb._create_imported_container("CIMU9990006", self.customer)

		booking = self._tank_in([
			{"container": imported, "condition": "EMPTY DIRTY", "is_new_container": 1},
			{"container": EXISTING, "condition": "EMPTY CLEAN"},
		])

		self.assertEqual(
			frappe.db.get_value("Container", imported, "created_by_booking"), booking.name
		)
		self.assertEqual(booking.items[0].is_new_container, 1)
		self.assertEqual(booking.items[1].is_new_container, 0)
		# ...and the save is also what reserves it: now there IS a booking to be Booked by.
		self.assertEqual(frappe.db.get_value("Container", imported, "status"), "Booked")

		# Re-saving must not un-badge the row it claimed — the flag is read off the
		# Container, not remembered from the branch that set it.
		booking.save(ignore_permissions=True)
		self.assertEqual(booking.items[0].is_new_container, 1)

	def test_a_hand_typed_number_still_gets_its_master_on_save(self):
		# The importer is not the only way in: a row typed straight onto the grid carries
		# only a number, and _resolve_containers still mints its master at save.
		booking = self._tank_in([{"container_no": "CIMU9990007", "condition": "EMPTY CLEAN"}])

		self.assertEqual(booking.items[0].container, "CIMU9990007")
		self.assertEqual(booking.items[0].is_new_container, 1)
		self.assertEqual(
			frappe.db.get_value("Container", "CIMU9990007", "created_by_booking"), booking.name
		)

	def test_a_claim_is_refused_for_a_tank_that_is_actually_in_the_depot(self):
		# The row's flag comes from the client, so it alone must never be enough to adopt a
		# real tank — cancelling the booking would then DELETE it.
		frappe.get_doc({
			"doctype": "Container",
			"container_no": EXISTING,
			"container_type": "ISO Tank",
			"status": "Available",
			"principal": self.customer,
		}).insert(ignore_permissions=True)

		booking = self._tank_in([
			{"container": EXISTING, "condition": "EMPTY CLEAN", "is_new_container": 1},
		])

		self.assertIsNone(frappe.db.get_value("Container", EXISTING, "created_by_booking"))
		self.assertEqual(booking.items[0].is_new_container, 0)
		# The booking still reserves it, as it always did — it just does not own it, so
		# cancelling releases the tank instead of deleting it.
		self.assertEqual(frappe.db.get_value("Container", EXISTING, "status"), "Booked")

	def test_an_imported_tank_passes_the_tank_in_submit_gate(self):
		# The Tank In submit gate refuses a container that is already in the depot. An
		# imported one is born Booked — announced, not present — so it goes through, which
		# it could not do if the importer registered it as a tank already on the ground.
		imported = cb._create_imported_container("CIMU9990010", self.customer)
		booking = self._tank_in(
			[{"container": imported, "condition": "EMPTY CLEAN", "is_new_container": 1}]
		)
		booking.submit()

		self.assertEqual(booking.docstatus, 1)
		self.assertEqual(booking.booking_status, "Confirmed")

	def test_cancelling_deletes_the_container_the_import_created(self):
		# What the claim buys: a tank that only exists because of this booking goes away
		# with it, instead of leaving a master for a tank that never arrived.
		imported = cb._create_imported_container("CIMU9990008", self.customer)
		booking = self._tank_in(
			[{"container": imported, "condition": "EMPTY CLEAN", "is_new_container": 1}]
		)
		booking.submit()
		cancel_submitted_booking(booking.name)

		self.assertFalse(frappe.db.exists("Container", imported))

	def test_parse_rejects_no_file(self):
		with self.assertRaises(frappe.ValidationError):
			cb.parse_container_xlsx(None)

	def test_template_and_master_are_downloads(self):
		cb.download_container_template()
		self.assertEqual(frappe.response.get("type"), "download")
		self.assertEqual(frappe.response.get("filename"), "container_import_template.xlsx")
		self.assertEqual(frappe.response["filecontent"][:2], b"PK")  # xlsx = zip magic

		frappe.response.clear()
		cb.download_container_master()
		self.assertEqual(frappe.response.get("type"), "download")
		self.assertEqual(frappe.response["filecontent"][:2], b"PK")
