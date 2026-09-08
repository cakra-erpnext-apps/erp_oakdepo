"""Cancel means the order never happened — so whatever it filed by itself comes back off.

Every order in the depot spins something up the moment it is approved: an EIR-In files a
Cleaning Order and an M&R, a Tank In bon arrives the tank into the yard, a Cleaning Order
holds the tank against the sweep that bills it. Cancelling them used to leave most of that
standing — a wash nobody ordered in the queue, a tank in the inventory that never came
through the gate, a voided order still landing on next month's invoice.

The EIR-Out half of the same rule (the departure, its gate log and its bon) lives in
``test_gate_out``; the survey day a voided booking calls off, in ``test_tank_survey``.

Self-cleaning: every fixture is hard-deleted in tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import container_activity as ca
from container_depot.container_depot import eir
from container_depot.container_depot.doctype.order_bongkar import order_bongkar as ob
from container_depot.container_depot.order_generation import revert_order_to_draft, void_order
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_container, _make_order_bongkar

PREFIX = "CNCL"
CUSTOMER = "Cancel Rollback Co"


def _purge():
	"""Drop everything this module can create, pointing rows before the rows they point at."""
	containers = frappe.get_all(
		"Container", filters={"name": ("like", f"{PREFIX}%")}, pluck="name"
	) or [""]
	inspections = frappe.get_all(
		"Inspection", filters={"container": ("in", containers)}, pluck="name"
	) or [""]
	for child in ("Inspection Damage Entry", "Inspection Item Photo", "Inspection Photo"):
		frappe.db.delete(child, {"parent": ("in", inspections)})
	orders = frappe.get_all(
		"Cleaning Order", filters={"container": ("in", containers)}, pluck="name"
	) or [""]
	repairs = frappe.get_all(
		"Repair Order", filters={"container": ("in", containers)}, pluck="name"
	) or [""]
	bons = frappe.get_all(
		"Container Booking Item",
		filters={"container": ("in", containers), "parenttype": "Order Bongkar"},
		pluck="parent", distinct=True,
	) or [""]
	bookings = frappe.get_all(
		"Container Booking Item",
		filters={"container": ("in", containers), "parenttype": "Container Booking"},
		pluck="parent", distinct=True,
	) or [""]
	for doctype, names in (
		("Inspection", inspections), ("Cleaning Order", orders), ("Repair Order", repairs),
		("Order Bongkar", bons), ("Container Booking", bookings),
	):
		frappe.db.delete("Notification Log", {"document_type": doctype, "document_name": ("in", names)})
	frappe.db.delete("Repair Damage Entry", {"parent": ("in", repairs)})
	frappe.db.delete("Cleaning Order Service", {"parent": ("in", orders)})
	frappe.db.delete("Inspection", {"name": ("in", inspections)})
	frappe.db.delete("Cleaning Order", {"name": ("in", orders)})
	frappe.db.delete("Repair Order", {"name": ("in", repairs)})
	frappe.db.delete("Container Booking Item", {"parent": ("in", bons + bookings)})
	# Both refuse delete_doc ("use Cancel to void it instead").
	frappe.db.delete("Order Bongkar", {"name": ("in", bons)})
	frappe.db.delete("Container Booking", {"name": ("in", bookings)})
	gates = frappe.get_all(
		"Gate Entry", filters={"container_no": ("like", f"{PREFIX}%")}, pluck="name"
	) or [""]
	# The CODECO segment a submitted gate entry writes onto its own timeline.
	frappe.db.delete("Comment", {"reference_doctype": "Gate Entry", "reference_name": ("in", gates)})
	frappe.db.delete("Gate Entry", {"name": ("in", gates)})
	for log in ("Container Movement", "Container Activity"):
		frappe.db.delete(log, {"container": ("in", containers)})
	frappe.db.delete("Container", {"name": ("like", f"{PREFIX}%")})
	frappe.db.commit()


class _Base(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_purge()
		self.customer = ensure_test_customer(CUSTOMER)

	def tearDown(self):
		frappe.set_user("Administrator")
		_purge()
		super().tearDown()

	def _container(self, no, **kw):
		return _make_container(f"{PREFIX}{no}", principal=self.customer, **kw)


# ---------------------------------------------------------------------------
class TestCleaningOrderCancel(_Base):
	def _completed_order(self, container):
		doc = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Completed",
		}).insert(ignore_permissions=True, ignore_mandatory=True)
		doc.submit()
		return doc.name

	def test_cancel_takes_the_order_out_of_the_billing_sweep(self):
		"""``consolidated_billing._cleaning_lines`` selects on ``status == "Completed"`` and
		never looks at docstatus, so an order whose status the cancel left alone was billed
		afterwards as if it had never been voided."""
		c = self._container("0000001")
		name = self._completed_order(c)

		frappe.get_doc("Cleaning Order", name).cancel()

		self.assertEqual(frappe.db.get_value("Cleaning Order", name, "status"), "Cancelled")

	def test_a_billed_cleaning_order_refuses_to_cancel(self):
		"""The rollback for a billed order lives on the INVOICE side, so the invoice is what
		has to go first — the same refusal ``cleaning.revert_to_draft`` makes."""
		c = self._container("0000002")
		name = self._completed_order(c)
		frappe.db.set_value("Cleaning Order", name, "sales_invoice", "SINV-TEST-0001", update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Cleaning Order", name).cancel()
		self.assertEqual(frappe.db.get_value("Cleaning Order", name, "docstatus"), 1)


# ---------------------------------------------------------------------------
class TestEirInVoid(_Base):
	"""Submitting an EIR-In files the follow-up work; voiding it says the inspection never
	happened, so the work it ordered must not stay on the depot's queues."""

	def _submitted_eir(self, container):
		return eir.create_eir(
			inspection_type="EIR-In", container=container, tank_status="Empty Dirty", submit=True
		)["name"]

	def _cleaning_order(self, container):
		return frappe.db.get_value("Cleaning Order", {"container": container}, ["name", "status"], as_dict=True)

	def test_voiding_drops_the_untouched_cleaning_order_it_filed(self):
		c = self._container("0000003")
		name = self._submitted_eir(c)
		self.assertEqual(self._cleaning_order(c).status, "Service Setup")

		frappe.get_doc("Inspection", name).cancel()

		self.assertEqual(self._cleaning_order(c).status, "Cancelled")
		# ...and with nothing open on it any more, the tank is free again.
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")

	def test_voiding_keeps_a_wash_the_crew_has_already_started(self):
		"""Only an order still exactly as it was born is dropped. A wash under way is real
		work — the tank has been steamed whatever the paperwork says afterwards."""
		c = self._container("0000004")
		name = self._submitted_eir(c)
		order = self._cleaning_order(c).name
		frappe.db.set_value(
			"Cleaning Order", order,
			{"status": "In_Progress", "cleaning_start": frappe.utils.now_datetime()},
			update_modified=False,
		)

		frappe.get_doc("Inspection", name).cancel()

		self.assertEqual(frappe.db.get_value("Cleaning Order", order, "status"), "In_Progress")
		# Open work still holds the tank.
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")


# ---------------------------------------------------------------------------
class TestBonArrivalUnwind(_Base):
	"""Submitting a Tank In bon is what puts the tank in the yard. Voiding it used to leave
	the tank there — counted in the inventory, offered to the next Tank Out booking, and
	impossible for the replacement bon to re-arrive."""

	def _arrived(self, no, **kw):
		"""A tank whose arrival was stamped by a bon, and that bon."""
		c = self._container(no, status="Booked", **kw)
		bon = _make_order_bongkar(self.customer, c)
		doc = frappe.get_doc("Order Bongkar", bon)
		ob._sync_container_arrival(doc)
		row = frappe.db.get_value("Container", c, ["status", "eir_in_date"], as_dict=True)
		self.assertIn(row.status, ("In_Depot", "Available"))
		self.assertTrue(row.eir_in_date)
		return c, doc

	def test_voiding_the_bon_un_arrives_the_tank(self):
		c, doc = self._arrived("0000005")

		doc.run_method("on_cancel")

		row = frappe.db.get_value("Container", c, ["status", "eir_in_date"], as_dict=True)
		# Gate_Out, never Available: a tank that did not arrive is not standing in the yard.
		self.assertEqual(row.status, "Gate_Out")
		self.assertIsNone(row.eir_in_date)
		# ...and the roll-back went through the ORM, so the tank's own status audit records
		# it. Written raw it would have left the Movement trail ending at In_Depot — a status
		# the tank no longer has — and the storage visit open on a stay that never happened.
		self.assertTrue(
			frappe.db.exists("Container Movement", {"container": c, "to_status": "Gate_Out"})
		)
		self.assertTrue(
			frappe.db.exists("Container Activity", {
				"container": c, "activity_type": "Status Change", "reference_name": doc.name,
			})
		)

	def test_a_tank_still_expected_goes_back_to_booked(self):
		"""The bon's Booking Codes went back to Active a moment ago, so a booking that is
		still standing is still expecting the tank."""
		c, doc = self._arrived("0000006")
		booking = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank In",
			"customer": self.customer, "booking_status": "Confirmed",
			"items": [{"container": c, "container_no": c}],
		})
		booking.flags.ignore_validate = True
		booking.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.set_value("Container Booking", booking.name, "docstatus", 1, update_modified=False)
		doc.booking = booking.name

		doc.run_method("on_cancel")

		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Booked")

	def test_work_under_way_keeps_the_arrival(self):
		"""A cleaning or an M&R is somebody working on a tank that is here — the depot does
		not get to un-arrive it because a piece of paperwork was voided."""
		c, doc = self._arrived("0000007")
		frappe.get_doc({
			"doctype": "Cleaning Order", "container": c, "status": "In_Progress",
		}).insert(ignore_permissions=True, ignore_mandatory=True)

		doc.run_method("on_cancel")

		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")
		self.assertTrue(frappe.db.get_value("Container", c, "eir_in_date"))

	def test_a_real_inspection_keeps_the_arrival(self):
		"""A submitted EIR-In against this bon means a surveyor stood at the tank — it really
		did arrive, whatever happens to the bon afterwards."""
		c, doc = self._arrived("0000008")
		eir.create_eir(
			inspection_type="EIR-In", container=c, tank_status="Empty Clean",
			referred_voucher=doc.name, submit=True,
		)

		doc.run_method("on_cancel")

		self.assertIn(frappe.db.get_value("Container", c, "status"), ("In_Depot", "Available"))
		self.assertTrue(frappe.db.get_value("Container", c, "eir_in_date"))

	def test_the_draft_road_unwinds_exactly_the_same(self):
		"""``revert_order_to_draft`` brings a SUBMITTED bon back to draft with everything its
		submit produced still standing, so voiding from there is not "a bon that never
		happened" — it has to unwind the same things the submitted road does. It used to
		release only the Booking Codes."""
		c, doc = self._arrived("0000009")
		draft_eir = frappe.get_doc({
			"doctype": "Inspection", "inspection_type": "EIR-In",
			"container": c, "inspector": "Administrator",
		})
		eir._apply_voucher(draft_eir, doc.name)
		draft_eir.insert(ignore_permissions=True)

		revert_order_to_draft(doc.name)
		void_order(doc.name)

		self.assertEqual(frappe.db.get_value("Order Bongkar", doc.name, "docstatus"), 2)
		# The draft EIR only existed because of this bon and was never started.
		self.assertFalse(frappe.db.exists("Inspection", draft_eir.name))
		row = frappe.db.get_value("Container", c, ["status", "eir_in_date"], as_dict=True)
		self.assertEqual(row.status, "Gate_Out")
		self.assertIsNone(row.eir_in_date)


# ---------------------------------------------------------------------------
class TestGateEntryCancel(_Base):
	"""A submitted Gate Entry is itself an arrival — ``on_submit`` puts the tank In_Depot and
	stamps its ``eir_in_date`` — and it had no cancel hook at all, so voiding one left the
	tank inside on a gate record that no longer existed."""

	def test_voiding_a_submitted_gate_entry_takes_the_arrival_back(self):
		c = self._container("0000010", status="Booked")
		ge = frappe.get_doc({
			"doctype": "Gate Entry", "container": c, "container_no": c,
			"gate_in_timestamp": frappe.utils.now_datetime(),
		})
		ge.insert(ignore_permissions=True, ignore_mandatory=True)
		ge.submit()
		self.assertIn(frappe.db.get_value("Container", c, "status"), ("In_Depot", "Available"))

		ge.cancel()

		row = frappe.db.get_value("Container", c, ["status", "eir_in_date"], as_dict=True)
		self.assertEqual(row.status, "Gate_Out")
		self.assertIsNone(row.eir_in_date)
		self.assertEqual(frappe.db.get_value("Gate Entry", ge.name, "status"), "Cancelled")

	def test_an_arrival_somebody_else_stamped_is_left_alone(self):
		"""The tank came in on a bon; this gate log is beside it, not the reason it is here."""
		c = self._container("0000011", status="Booked")
		bon = _make_order_bongkar(self.customer, c)
		ob._sync_container_arrival(frappe.get_doc("Order Bongkar", bon))
		ge = frappe.get_doc({
			"doctype": "Gate Entry", "container": c, "container_no": c,
			"gate_in_timestamp": frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=1),
			"status": "Gate_In_Completed",
		})
		ge.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.set_value("Gate Entry", ge.name, "docstatus", 1, update_modified=False)

		frappe.get_doc("Gate Entry", ge.name).cancel()

		self.assertIn(frappe.db.get_value("Container", c, "status"), ("In_Depot", "Available"))
		self.assertTrue(frappe.db.get_value("Container", c, "eir_in_date"))


# ---------------------------------------------------------------------------
class TestActivityFeedMarksVoids(_Base):
	"""The timeline is append-only, so a cancel neither deletes nor rewrites the row it
	undoes — the depot's record of what was done has to survive being taken back. But an
	unmarked row READS as a fact: a voided EIR-Out still says "Gate-out / load complete".
	So the void is derived from the source document at read time and shown on the row."""

	def _rows(self, container):
		return frappe.get_all(
			"Container Activity", filters={"container": container},
			fields=["name", "activity_type", "summary", "reference_doctype", "reference_name"],
			order_by="creation asc",
		)

	def test_the_submit_row_survives_the_cancel_and_is_flagged(self):
		c = self._container("0000012")
		name = eir.create_eir(
			inspection_type="EIR-In", container=c, tank_status="Empty Clean", submit=True
		)["name"]
		before = ca.annotate_voided(self._rows(c))
		submit_row = next(r for r in before if r.reference_name == name)
		self.assertFalse(submit_row["voided"])

		frappe.get_doc("Inspection", name).cancel()

		after = ca.annotate_voided(self._rows(c))
		# Still there — nothing is deleted — and now marked.
		still = next(r for r in after if r.reference_name == name and r.name == submit_row.name)
		self.assertTrue(still["voided"])

	def test_the_cancel_writes_its_own_row(self):
		"""...and the undo is an event in its own right, so the feed says WHEN it happened
		rather than only that the old row no longer counts."""
		c = self._container("0000013")
		name = eir.create_eir(
			inspection_type="EIR-In", container=c, tank_status="Empty Clean", submit=True
		)["name"]
		count = len(self._rows(c))

		frappe.get_doc("Inspection", name).cancel()

		rows = self._rows(c)
		self.assertGreater(len(rows), count)
		self.assertTrue(any("dibatalkan" in (r.summary or "") for r in rows))

	def test_a_row_with_no_source_document_is_never_void(self):
		"""A bare status change has nothing that could have been undone."""
		c = self._container("0000014")
		ca.log_container_activity(c, "Status Change", from_status="Booked", to_status="In_Depot")
		rows = ca.annotate_voided(self._rows(c))
		self.assertFalse(any(r["voided"] for r in rows))
