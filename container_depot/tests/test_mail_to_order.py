"""Email → Order bridge: container list in, a prefilled Booking / Gate Out Plan out.

One customer mail names several tanks, so the bridge is list-shaped end to end. What is
covered here is the part an operator would notice if it broke:

* the numbers are read out of the mail body and out of whatever the operator pastes back
  (line breaks, commas, "TEMU 1234567" with a space, non-ISO depot numbers);
* each number is resolved against the Container master *before* anything is built, and
  judged by the booking's own direction gate — Tank In may announce a tank that does not
  exist yet, Tank Out may not;
* an imported file may only name tanks the master already knows;
* the order comes back as one prefilled, unsaved form with a row per container — the bridge
  writes nothing at all.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from container_depot.container_depot.mail_to_order import (
	download_container_template,
	get_order_prefill,
	linked_orders,
	parse_container_file,
	parse_container_input,
	parse_container_rows,
	resolve_containers,
	scan_email_containers,
)
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _ensure_cargo, _make_container

_DEPOT = "OAK1"
_A = "MTOU1000001"
_B = "MTOU1000002"
_GHOST = "MTOU9999999"  # deliberately never created


class TestMailToOrder(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._principal = ensure_test_customer("MailToOrder Test Principal")
		self._containers = []
		self._comms = []
		self._files = []

	def tearDown(self):
		for c in self._containers:
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Repair Order", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		for f in self._files:
			frappe.delete_doc("File", f, force=True, ignore_permissions=True)
		for cm in self._comms:
			frappe.db.delete("Cleaning Order", {"reff_email": cm})
			frappe.db.delete("Repair Order", {"reff_email": cm})
			frappe.db.delete("Communication", {"name": cm})
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno, **kw):
		kw.setdefault("principal", self._principal)
		kw.setdefault("depot", _DEPOT)
		name = _make_container(cno, **kw)
		self._containers.append(name)
		return name

	def _email(self, content, subject="Permintaan cleaning"):
		comm = frappe.get_doc({
			"doctype": "Communication", "communication_type": "Communication",
			"communication_medium": "Email", "sent_or_received": "Received",
			"subject": subject, "content": content, "sender": "ops@example.com",
		}).insert(ignore_permissions=True)
		self._comms.append(comm.name)
		return comm.name

	# --- parsing --------------------------------------------------------------
	def test_parse_splits_on_lines_and_commas_not_spaces(self):
		"""A space inside a number is part of the number; a space between two whole
		numbers is not. Both spellings appear in real mails."""
		self.assertEqual(
			parse_container_input("MTOU 1000001\nMTOU-1000002, MTOU1000003"),
			["MTOU1000001", "MTOU1000002", "MTOU1000003"],
		)
		self.assertEqual(
			parse_container_input("MTOU1000001 MTOU1000002"),
			["MTOU1000001", "MTOU1000002"],
		)

	def test_parse_keeps_non_iso_numbers_and_dedupes(self):
		# The Container master does not length-check, so a hand-typed odd number must
		# survive verbatim instead of being silently dropped.
		self.assertEqual(
			parse_container_input("tank-7\nMTOU1000001\nmtou1000001"),
			["TANK7", "MTOU1000001"],
		)

	def test_parse_accepts_a_list(self):
		self.assertEqual(parse_container_input(["mtou1000001"]), ["MTOU1000001"])

	def test_parse_rows_keeps_per_row_fields(self):
		"""The dialog sends its grid; the row's own cargo has to survive the trip."""
		rows = parse_container_rows([
			{"container": _A, "container_no": "mtou 1000001", "cargo": "Methanol"},
			{"container_no": "MTOU1000002"},
			{"container_no": "MTOU1000002"},  # duplicate row — collapsed
			{"container_no": ""},             # blank row — dropped
		])
		self.assertEqual(
			rows,
			[{"container_no": _A, "cargo": "Methanol"}, {"container_no": "MTOU1000002"}],
		)

	def test_parse_rows_falls_back_to_the_text_blob(self):
		self.assertEqual(
			parse_container_rows("MTOU1000001, MTOU1000002"),
			[{"container_no": "MTOU1000001"}, {"container_no": "MTOU1000002"}],
		)

	def _xlsx(self, rows):
		"""An .xlsx attachment holding ``rows`` — the shape the dialog's importer reads."""
		import io

		import xlsxwriter

		buffer = io.BytesIO()
		book = xlsxwriter.Workbook(buffer, {"in_memory": True})
		sheet = book.add_worksheet("Containers")
		for r, cells in enumerate(rows):
			for c, value in enumerate(cells):
				sheet.write(r, c, value)
		book.close()
		doc = frappe.get_doc({
			"doctype": "File", "file_name": "mto-test.xlsx",
			"content": buffer.getvalue(), "is_private": 1,
		}).insert(ignore_permissions=True)
		self._files.append(doc.name)
		return doc.file_url

	# --- reading an uploaded file ---------------------------------------------
	def test_file_import_only_accepts_tanks_the_master_knows(self):
		"""A spreadsheet is where typo'd tank numbers come from: an unknown one is refused
		and named, never imported as loose text and never turned into a master."""
		cargo = _ensure_cargo("MailToOrder Test Cargo")
		self._container(_A)
		self._container(_B)
		url = self._xlsx([
			["Container", "Last Cargo"],             # header — skipped
			["mtou 1000001", cargo],                 # spaced + lowercase, known tank
			[_GHOST, ""],                            # no master — refused
			[_GHOST, ""],                            # duplicate — collapsed
			["MTOU1000002", "Tidak Ada Cargo Ini"],  # bad cargo: real tank, row kept
		])

		res = parse_container_file(url)

		self.assertEqual(
			[(r["container_no"], r["container"], r["cargo"]) for r in res["rows"]],
			[(_A, _A, cargo), (_B, _B, None)],
		)
		self.assertEqual(res["skipped"], [_GHOST])
		self.assertFalse(frappe.db.exists("Container", {"container_no": _GHOST}))
		self.assertEqual(len(res["errors"]), 1)
		self.assertIn("Tidak Ada Cargo Ini", res["errors"][0])

	def test_file_import_needs_a_file(self):
		with self.assertRaises(frappe.ValidationError):
			parse_container_file("")

	def test_template_is_a_download(self):
		"""What the dialog's Download Template button streams back."""
		try:
			download_container_template()
			self.assertEqual(frappe.response.get("type"), "download")
			self.assertEqual(frappe.response.get("filename"), "container_email_template.xlsx")
			self.assertEqual(frappe.response["filecontent"][:2], b"PK")  # xlsx = zip magic
		finally:
			frappe.response.clear()

	# --- reading the mail -----------------------------------------------------
	def test_scan_reads_numbers_out_of_subject_and_body(self):
		self._container(_A)
		comm = self._email(
			f"<p>Mohon dicleaning:</p><ul><li>{_A}</li><li>{_GHOST}</li></ul>",
			subject=f"Cleaning {_A}",
		)
		rows = scan_email_containers(comm)
		self.assertEqual([r["container_no"] for r in rows], [_A, _GHOST])
		self.assertTrue(rows[0]["known"])
		self.assertFalse(rows[1]["known"])

	def test_resolve_flags_unknown_and_tank_in_autocreate(self):
		self._container(_A, status="Available")
		rows = resolve_containers(f"{_A}\n{_GHOST}", order_type="Cleaning")
		self.assertEqual(rows[0]["status"], "Available")
		self.assertEqual(rows[0]["depot"], _DEPOT)
		self.assertFalse(rows[1]["known"])
		self.assertFalse(rows[1]["will_create"])
		# A Tank In booking creates the pre-arrival master itself on save, so the same
		# unknown number is not a problem there.
		booking_rows = resolve_containers(_GHOST, order_type="Booking", direction="Tank In")
		self.assertTrue(booking_rows[0]["will_create"])
		self.assertFalse(
			resolve_containers(_GHOST, order_type="Booking", direction="Tank Out")[0]["will_create"]
		)

	def test_tank_out_refuses_a_number_with_no_master(self):
		"""Tank Out never mints a tank: an unknown number is a dead end, not a promise."""
		row = resolve_containers(_GHOST, order_type="Booking", direction="Tank Out")[0]
		self.assertFalse(row["will_create"])
		self.assertIn("wajib pilih dari master", row["blocked"])

	def test_tank_out_blocks_a_tank_that_is_not_in_the_depot(self):
		self._container(_A, status="Gate_Out")
		row = resolve_containers(_A, order_type="Booking", direction="Tank Out")[0]
		self.assertIn("tidak ada di depo", row["blocked"])

	def test_tank_out_blocks_a_tank_with_work_still_open(self):
		"""Readiness is the absence of open work — not the cached Available status."""
		self._container(_A, status="Available")
		self.assertIsNone(resolve_containers(_A, order_type="Booking", direction="Tank Out")[0]["blocked"])

		order = frappe.get_doc({
			"doctype": "Cleaning Order", "container": _A, "status": "Pending",
		}).insert(ignore_permissions=True)
		self.addCleanup(frappe.db.delete, "Cleaning Order", {"name": order.name})

		row = resolve_containers(_A, order_type="Booking", direction="Tank Out")[0]
		self.assertIn("order belum selesai", row["blocked"])

	def test_tank_in_may_name_a_new_tank_but_not_one_already_here(self):
		self.assertTrue(
			resolve_containers(_GHOST, order_type="Booking", direction="Tank In")[0]["will_create"]
		)
		self._container(_A, status="In_Depot")
		row = resolve_containers(_A, order_type="Booking", direction="Tank In")[0]
		self.assertIn("sudah ada di depo", row["blocked"])

	def test_direction_gates_are_booking_only(self):
		"""A gate-out PLAN is a prep notice, not a movement — it has no direction to fail."""
		self._container(_A, status="In_Depot")
		self.assertIsNone(resolve_containers(_A, order_type="Gate Out")[0]["blocked"])

	# --- table-shaped orders: one prefilled form, nothing written -------------
	def test_booking_prefill_builds_one_row_per_container(self):
		self._container(_A)
		comm = self._email("Booking untuk 2 tank")
		before = frappe.db.count("Container Booking")

		res = get_order_prefill(
			comm, "Booking", containers=f"{_A}\n{_GHOST}",
			options={"direction": "Tank In", "tanggal_bongkar": today()},
		)

		self.assertEqual(res["doctype"], "Container Booking")
		self.assertEqual(res["table"]["fieldname"], "items")
		self.assertEqual(res["table"]["doctype"], "Container Booking Item")
		rows = res["table"]["rows"]
		self.assertEqual([r["container_no"] for r in rows], [_A, _GHOST])
		self.assertEqual(rows[0]["container"], _A)
		# Unknown number carries no link — the booking mints the master on save.
		self.assertNotIn("container", rows[1])
		# Condition is not something an email states — every line starts Empty Dirty and is
		# corrected on the booking form, which is why the dialog stopped asking.
		self.assertEqual(rows[0]["condition"], "EMPTY DIRTY")
		self.assertEqual(rows[0]["tanggal_bongkar"], today())
		self.assertEqual(res["values"]["direction"], "Tank In")
		self.assertEqual(res["values"]["reff_email"], comm)
		self.assertEqual(before, frappe.db.count("Container Booking"))

	def test_booking_prefill_takes_reff_doc_and_per_row_cargo(self):
		"""No. Dokumen is typed off the mail; the cargo is per tank, on the booking line."""
		cargo = _ensure_cargo("MailToOrder Test Cargo")
		self._container(_A)
		self._container(_B)
		comm = self._email("Booking 2 tank")

		res = get_order_prefill(
			comm, "Booking",
			containers=[
				{"container": _A, "container_no": _A, "cargo": cargo},
				{"container_no": _B},
			],
			options={"reff_doc": "SPK-8891"},
		)

		self.assertEqual(res["values"]["reff_doc"], "SPK-8891")
		rows = res["table"]["rows"]
		self.assertEqual(rows[0]["cargo"], cargo)
		self.assertNotIn("cargo", rows[1])

	def test_cargo_never_lands_on_an_order_whose_lines_have_none(self):
		"""Gate Out lines have no cargo field; the grid column is context there, not data."""
		cargo = _ensure_cargo("MailToOrder Test Cargo")
		self._container(_A)
		comm = self._email("Lift on")
		res = get_order_prefill(comm, "Gate Out", containers=[{"container_no": _A, "cargo": cargo}])
		self.assertNotIn("cargo", res["table"]["rows"][0])

	def test_resolve_reports_the_masters_last_cargo(self):
		"""The grid prefills its Last Cargo column from this."""
		cargo = _ensure_cargo("MailToOrder Test Cargo")
		self._container(_A, last_cargo=cargo)
		self.assertEqual(resolve_containers(_A)[0]["last_cargo"], cargo)

	def test_prefill_takes_the_picked_principal_over_the_guess(self):
		"""The header's Tank Owner is a deliberate pick — it beats the sender lookup, and it
		is who a Tank In booking's pre-arrival Containers are born under."""
		owner = ensure_test_customer("MailToOrder Test Owner")
		self._container(_A)
		comm = self._email("Booking")

		booking = get_order_prefill(comm, "Booking", containers=[_A], options={"principal": owner})
		self.assertEqual(booking["values"]["principal"], owner)

		# Gate Out resolves its principal from the sender / the tanks; the pick still wins.
		gate_out = get_order_prefill(comm, "Gate Out", containers=[_A], options={"principal": owner})
		self.assertEqual(gate_out["values"]["principal"], owner)

	def test_prefill_seeds_depot_and_principal_only_when_unanimous(self):
		self._container(_A)
		self._container(_B)
		comm = self._email("Siap lift on")

		res = get_order_prefill(comm, "Gate Out", containers=f"{_A}\n{_B}",
							   options={"target_lift_on": today()})
		self.assertEqual(res["values"]["depot"], _DEPOT)
		self.assertEqual(res["values"]["principal"], self._principal)
		self.assertEqual(res["table"]["fieldname"], "containers")
		self.assertEqual([r["target_lift_on"] for r in res["table"]["rows"]], [today(), today()])

		# Mixed depots must not be guessed.
		other = self._container("MTOU1000003", depot="OAK2")
		mixed = get_order_prefill(comm, "Gate Out", containers=f"{_A}\n{other}")
		self.assertNotIn("depot", mixed["values"])

	def test_only_booking_and_gate_out_can_be_raised(self):
		"""Cleaning / M&R / Survey are depot decisions, not something a mail books."""
		comm = self._email("Halo")
		for order_type in ("Tidak Ada", "Cleaning", "M&R", "Survey"):
			with self.assertRaises(frappe.ValidationError):
				get_order_prefill(comm, order_type)

	def test_orders_from_a_type_no_longer_offered_are_still_listed(self):
		"""The read side is wider than the write side: an email that became a Cleaning Order
		back when it could must not look untouched."""
		self._container(_A)
		comm = self._email("Cleaning lama")
		order = frappe.get_doc({
			"doctype": "Cleaning Order", "container": _A, "reff_email": comm,
		}).insert(ignore_permissions=True)
		self.addCleanup(frappe.db.delete, "Cleaning Order", {"name": order.name})

		listed = linked_orders(comm)
		self.assertIn(("Cleaning Order", order.name), [(o["doctype"], o["name"]) for o in listed])
