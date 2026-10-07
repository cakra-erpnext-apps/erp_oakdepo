"""One container, one open booking.

The status gates never caught a double booking: a Tank In tank sits at ``Booked``
(not in ``PRESENT``) and a Tank Out booking leaves the tank on ``Available``, so in
both directions a second booking submitted cleanly and the gate ended up holding two
live Booking Codes for the same tank.

The guard keys off the Booking Code instead — ``Active`` means "confirmed, no bon
yet". A ``Used`` code goes on holding the tank until the tank actually MOVES: the code is
consumed on the bon's first DRAFT save, which is paperwork, not an arrival. Cancelling the
booking voids its codes and releases the tank outright. Each release path has its own test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests._booking_helpers import cancel_submitted_booking

CUSTOMER = "Double Booking Co"
C_IN = "DBGU1110001"
C_OUT = "DBGU1110002"
CONTAINERS = (C_IN, C_OUT)


def _purge(doctype: str, filters: dict, children: tuple = ()):
	names = frappe.get_all(doctype, filters=filters, pluck="name")
	if not names:
		return
	frappe.db.delete("Notification Log", {"document_type": doctype, "document_name": ("in", names)})
	for child in children:
		frappe.db.delete(child, {"parent": ("in", names)})
	frappe.db.delete(doctype, {"name": ("in", names)})


def _cleanup():
	by_customer = {"customer": CUSTOMER}
	bookings = frappe.get_all("Container Booking", filters=by_customer, pluck="name")
	if bookings:
		frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
		# Bons first: they hang off the bookings, and a submitted one drags the arrival
		# paperwork (gate log + auto-provisioned EIR) along with it. Raw deletes on
		# purpose — Order Bongkar refuses ``on_trash`` by design.
		_purge("Order Bongkar", {"booking": ("in", bookings)}, ("Container Booking Item",))
		# Saving an outbound booking schedules one Survey Order, with a row per tank
		# (provisioning happens on the draft), so they belong to this purge too.
		_purge("Survey Order", {"booking": ("in", bookings)}, ("Survey Order Tank",))
	_purge("Gate Entry", {"container_no": ("in", CONTAINERS)})
	_purge("Inspection", {"container": ("in", CONTAINERS)},
		   ("Inspection Item Photo", "Inspection Damage Entry", "Inspection Damage Photo",
		    "Inspection Seal", "Repair Estimate Item", "Inspection Photo"))
	_purge("Container Booking", by_customer, ("Container Booking Item",))
	# Both audit logs, not just movements: submitting a booking writes a Container
	# Activity row too, and leaving those behind strands them on a deleted container.
	for log in ("Container Movement", "Container Activity"):
		frappe.db.delete(log, {"container": ("in", CONTAINERS)})
	_purge("Container", {"name": ("in", CONTAINERS)})
	_purge("Depot Contract", by_customer, ("Tariff Rate",))
	invoices = frappe.get_all("Sales Invoice", filters=by_customer, pluck="name")
	if invoices:
		frappe.db.sql(
			"DELETE FROM `tabGL Entry` WHERE voucher_type='Sales Invoice' AND voucher_no IN %(n)s",
			{"n": tuple(invoices)},
		)
	_purge("Sales Invoice", by_customer,
		   ("Sales Invoice Item", "Sales Taxes and Charges", "Payment Schedule"))
	if frappe.db.exists("Customer", CUSTOMER):
		frappe.db.delete("Customer", {"name": CUSTOMER})
	frappe.db.commit()


class TestBookingDoubleGuard(FrappeTestCase):
	# Per-method setUp/tearDown: submitting a booking commits (invoice + notifications),
	# bypassing FrappeTestCase's per-test rollback.
	def setUp(self):
		# Purge before creating: _cleanup removes the Customer this test builds on.
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)
		self.contract = frappe.get_doc({
			"doctype": "Depot Contract",
			"customer": self.customer,
			"currency": "IDR",
			"status": "Active",
			"payment_type": "TOP",
			"payment_terms": "NET 30",
			"credit_limit": 10_000_000,
			"valid_from": today(),
			"valid_to": add_days(today(), 365),
			"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		_cleanup()

	def _book(self, container_no, direction="Tank In", submit=True):
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": direction,
			"customer": self.customer,
			"contract": self.contract,
			"do_reference": "DO-DBG",
			"do_document": "/files/do.pdf",
			# Outbound bookings refuse to save without their plan date; inbound ignores it.
			"plan_date": today(),
			"items": [{"container_no": container_no}],
		}).insert(ignore_permissions=True)
		if submit:
			b.submit()
		return b

	def _available_container(self, cno):
		return frappe.get_doc({
			"doctype": "Container",
			"container_no": cno,
			"container_type": "ISO Tank",
			"status": "Available",
			"principal": self.customer,
		}).insert(ignore_permissions=True).name

	def _arrived_container(self, cno):
		"""A tank that really came in through the gate. ``in_date`` is the difference
		that matters here: it is what stops ``_mark_pre_arrival`` flipping the tank to
		``Booked`` when an inbound booking names it, so the status stays the truth about
		where the tank is."""
		name = self._available_container(cno)
		frappe.db.set_value(
			"Container", name, {"status": "In_Depot", "in_date": today()}, update_modified=False
		)
		return name

	def test_second_tank_in_booking_is_blocked(self):
		first = self._book(C_IN)
		# The tank sits at Booked, which the presence gate lets through — this guard is
		# the only thing standing between it and a second live code.
		self.assertEqual(frappe.db.get_value("Container", C_IN, "status"), "Booked")

		with self.assertRaises(frappe.ValidationError) as cm:
			self._book(C_IN)
		self.assertIn(first.name, str(cm.exception))
		self.assertEqual(frappe.db.count("Booking Code", {"container_no": C_IN, "state": "Active"}), 1)

	def test_second_tank_out_booking_is_blocked(self):
		self._available_container(C_OUT)
		first = self._book(C_OUT, "Tank Out")
		# A Tank Out booking leaves the tank Available, so the readiness gate passes too.
		self.assertEqual(frappe.db.get_value("Container", C_OUT, "status"), "Available")

		with self.assertRaises(frappe.ValidationError) as cm:
			self._book(C_OUT, "Tank Out")
		self.assertIn(first.name, str(cm.exception))

	def _bon(self, booking, submit=False):
		"""The Order Bongkar an operator raises off a confirmed Tank In booking.

		Saving it as a draft is what consumes the Booking Code (``_reconcile_codes`` runs
		from ``on_update``) — which is exactly the state this guard has to survive.
		"""
		codes = frappe.get_all("Booking Code", filters={"booking": booking.name}, pluck="name")
		bon = frappe.get_doc({
			"doctype": "Order Bongkar",
			"booking": booking.name,
			"order_status": "Issued",
			"tanggal_bongkar": today(),
			"principal": self.customer,
			"containers": [{
				"container": row.container,
				"container_no": row.container_no,
				"condition": row.condition,
				"booking_code": code,
			} for row, code in zip(booking.items, codes)],
		}).insert(ignore_permissions=True)
		if submit:
			bon.submit()
		return bon

	def test_a_draft_bon_still_blocks(self):
		"""The code turns ``Used`` the moment the bon is SAVED, which is paperwork — the
		tank has not arrived. Releasing the reservation there let a second Tank In booking
		through for a tank that was still standing outside the depot."""
		first = self._book(C_IN)
		self._bon(first)  # draft only
		self.assertEqual(
			frappe.db.get_value("Booking Code", {"booking": first.name}, "state"), "Used"
		)
		self.assertEqual(frappe.db.get_value("Container", C_IN, "status"), "Booked")

		with self.assertRaises(frappe.ValidationError) as cm:
			self._book(C_IN)
		self.assertIn(first.name, str(cm.exception))

	def test_a_submitted_bon_stops_blocking_once_the_tank_leaves_again(self):
		"""...and the hold must lift once the tank really moved, or the next cycle's
		booking could never be raised. Submitting the bon IS the arrival; the tank then
		does its visit and gates out, and booking it back in is legitimate."""
		first = self._book(C_IN)
		self._bon(first, submit=True)
		# The bon's submit brought the tank in for real.
		self.assertEqual(frappe.db.get_value("Container", C_IN, "status"), "In_Depot")
		# ...it finished its visit and left.
		frappe.db.set_value("Container", C_IN, "status", "Gate_Out", update_modified=False)

		self._book(C_IN)  # must not raise

	def test_a_cancelled_booking_no_longer_blocks(self):
		first = self._book(C_IN)
		first.reload()
		cancel_submitted_booking(first.name)

		self._book(C_IN)  # must not raise

	def test_a_draft_blocks_too(self):
		"""A draft reserves its tanks from the moment it is saved. Booking Codes are only
		issued at submit, so the code-based half of the guard cannot see a draft — the
		draft rows are queried directly (``_draft_booking_holders``). Without this, two
		operators could each prepare a booking for the same tank and only collide at
		submit, with the paperwork already done."""
		self._book(C_IN, submit=False)
		with self.assertRaises(frappe.ValidationError):
			self._book(C_IN)

	def test_an_abandoned_inbound_draft_does_not_block_the_tank_leaving(self):
		"""The tank is HERE. Whatever an unsubmitted Tank In draft was going to do about
		bringing it in, that already happened — so it has nothing left to reserve and must
		not stand in the way of booking the tank out.

		Left unguarded this was a dead end with no exit on the booking screen: the outbound
		booking was refused, and the draft holding it was somebody else's half-finished
		paperwork that the operator had no reason to look for."""
		self._arrived_container(C_OUT)
		self._book(C_OUT, direction="Tank In", submit=False)
		self._book(C_OUT, direction="Tank Out")  # must not raise

	def test_a_spent_outbound_draft_does_not_block_the_tank_coming_back(self):
		"""The mirror image: the tank has left, so an unsubmitted Tank Out draft describes
		a departure that is already done and cannot refuse the tank's return."""
		name = self._available_container(C_OUT)
		self._book(C_OUT, direction="Tank Out", submit=False)
		frappe.db.set_value("Container", name, "status", "Gate_Out", update_modified=False)
		self._book(C_OUT, direction="Tank In")  # must not raise

	def test_two_outbound_drafts_on_a_present_tank_still_collide(self):
		"""The guard the direction test must not cost: while the tank is still standing in
		the depot, both outbound drafts are live claims on the same move."""
		self._available_container(C_OUT)
		self._book(C_OUT, direction="Tank Out", submit=False)
		with self.assertRaises(frappe.ValidationError):
			self._book(C_OUT, direction="Tank Out")

	# --- draft-time early warning (open_booking_conflicts) ---------------
	def test_warning_names_the_clashing_booking(self):
		"""The draft banner uses the same query as the submit block, so it can only warn
		about what Submit would actually refuse."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			open_booking_conflicts,
		)

		first = self._book(C_IN)
		# A different (still-unsaved) booking looking at the same container.
		warn = open_booking_conflicts("new-unsaved", [{"container_no": C_IN}])
		self.assertEqual(len(warn), 1)
		self.assertEqual(warn[0]["booking"], first.name)
		self.assertEqual(warn[0]["direction"], "Tank In")

	def test_warning_excludes_the_booking_itself(self):
		"""A booking must not warn about its own codes, or every saved booking would flag
		itself."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			open_booking_conflicts,
		)

		first = self._book(C_IN)
		self.assertEqual(open_booking_conflicts(first.name, [{"container_no": C_IN}]), [])

	def test_warning_is_silent_without_a_conflict(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			open_booking_conflicts,
		)

		self.assertEqual(open_booking_conflicts(None, [{"container_no": C_IN}]), [])

	# --- draft-time status↔direction warning (status_direction_warnings) -
	def test_status_warning_lift_on_needs_available(self):
		"""Tank Out (Lift On): a tank that is not Available is flagged (it is not ready to
		leave). Uses the same helper as the _validate_out_ready submit gate."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			status_direction_warnings,
		)

		self._available_container(C_OUT)
		rows = [{"container_no": C_OUT}]
		self.assertEqual(status_direction_warnings("Tank Out", rows), [])  # Available -> silent

		frappe.db.set_value("Container", C_OUT, "status", "Booked", update_modified=False)
		warn = status_direction_warnings("Tank Out", rows)
		self.assertEqual(len(warn), 1)
		self.assertEqual(warn[0]["direction"], "Tank Out")
		self.assertEqual(warn[0]["status"], "Booked")

	def test_status_warning_lift_off_rejects_present(self):
		"""Tank In (Lift Off): a tank already in the depot is flagged; a Booked (not yet
		arrived) one is fine. Same helper as the _validate_in_not_present submit gate."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			status_direction_warnings,
		)

		self._available_container(C_OUT)
		frappe.db.set_value("Container", C_OUT, "status", "Booked", update_modified=False)
		rows = [{"container_no": C_OUT}]
		self.assertEqual(status_direction_warnings("Tank In", rows), [])  # Booked -> silent

		frappe.db.set_value("Container", C_OUT, "status", "In_Depot", update_modified=False)
		warn = status_direction_warnings("Tank In", rows)
		self.assertEqual(len(warn), 1)
		self.assertEqual(warn[0]["direction"], "Tank In")

	def test_status_warning_silent_for_a_nonexistent_container(self):
		"""A Tank In may name a not-yet-created tank; with no master to judge, no warning."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			status_direction_warnings,
		)

		self.assertEqual(status_direction_warnings("Tank In", [{"container_no": "NOSUCH0000000"}]), [])

	# --- opposite directions: one open Tank In AND one open Tank Out per tank ----
	# Booked ahead of the other move, never two in the same direction, and the bon keeps
	# them in physical order — so a tank can never come in twice or go out twice.

	def test_tank_on_its_way_in_can_be_booked_out(self):
		inbound = self._book(C_IN)
		self.assertEqual(frappe.db.get_value("Container", C_IN, "status"), "Booked")
		outbound = self._book(C_IN, "Tank Out")  # must not raise
		self.assertEqual(outbound.docstatus, 1)
		self.assertEqual(frappe.db.count("Booking Code", {"container_no": C_IN, "state": "Active"}), 2)

		# ...but never a second one out.
		with self.assertRaises(frappe.ValidationError) as cm:
			self._book(C_IN, "Tank Out")
		self.assertIn(outbound.name, str(cm.exception))
		self.assertNotIn(inbound.name, str(cm.exception))

	def test_a_tank_nobody_is_bringing_in_still_cannot_be_booked_out(self):
		name = self._available_container(C_OUT)
		frappe.db.set_value("Container", name, "status", "Gate_Out", update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			self._book(C_OUT, "Tank Out")

	def test_tank_here_can_be_booked_back_in(self):
		self._arrived_container(C_OUT)
		outbound = self._book(C_OUT, "Tank Out")
		self._book(C_OUT, "Tank In")  # must not raise
		# The tank did not move: booking its return is paperwork, not an arrival.
		self.assertEqual(frappe.db.get_value("Container", C_OUT, "status"), "In_Depot")

		with self.assertRaises(frappe.ValidationError):
			self._book(C_OUT, "Tank In")
		self.assertTrue(outbound.name)

	def test_tank_here_without_an_outbound_still_cannot_be_booked_in(self):
		self._arrived_container(C_OUT)
		with self.assertRaises(frappe.ValidationError):
			self._book(C_OUT, "Tank In")

	def test_bon_muat_waits_for_the_tank_to_arrive(self):
		from container_depot.container_depot.order_generation import make_order

		self._book(C_IN)
		outbound = self._book(C_IN, "Tank Out")
		code = frappe.db.get_value("Booking Code", {"booking": outbound.name}, "name")
		with self.assertRaises(frappe.ValidationError) as cm:
			make_order(outbound.name, [code])
		self.assertIn("belum ada di depo", str(cm.exception))

	def test_a_bon_muat_on_the_outbound_still_lets_the_return_be_booked(self):
		"""The screenshot case (user, 2026-10-02): tanks booked out and already on a bon
		muat that is not submitted yet. Booking them back IN is the agreed 1 In + 1 Out;
		only a SECOND Tank Out is refused."""
		from container_depot.container_depot.order_generation import make_order

		self._arrived_container(C_OUT)
		outbound = self._book(C_OUT, "Tank Out")
		make_order(outbound.name, frappe.get_all("Booking Code", {"booking": outbound.name}, pluck="name"))
		self.assertEqual(frappe.db.get_value("Booking Code", {"booking": outbound.name}, "state"), "Used")

		self._book(C_OUT, "Tank In")  # must not raise
		with self.assertRaises(frappe.ValidationError) as cm:
			self._book(C_OUT, "Tank Out")
		# Names what to open — the holding booking AND its bon — and what to change.
		msg = str(cm.exception)
		bon = frappe.db.get_value("Order Muat", {"booking": outbound.name}, "name")
		self.assertIn(outbound.name, msg)
		self.assertIn(bon, msg)
		self.assertIn("hapus baris tank ini", msg)
		self.assertIn("gate-out", msg)  # not "submit bon": that moves nothing on a Tank Out

	def test_bon_bongkar_waits_for_the_tank_to_leave(self):
		self._arrived_container(C_OUT)
		self._book(C_OUT, "Tank Out")
		inbound = self._book(C_OUT, "Tank In")
		with self.assertRaises(frappe.ValidationError) as cm:
			self._bon(inbound)
		self.assertIn("masih ada di depo", str(cm.exception))

	def test_gate_scan_offers_only_the_move_that_can_happen_now(self):
		from container_depot.api import _find_active_bookings_for_container

		self._book(C_IN)
		self._book(C_IN, "Tank Out")
		# Not here yet: only arriving is possible.
		self.assertEqual({r.direction for r in _find_active_bookings_for_container(C_IN)}, {"Tank In"})

		self._arrived_container(C_OUT)
		self._book(C_OUT, "Tank Out")
		self._book(C_OUT, "Tank In")
		# Here: only leaving is possible.
		self.assertEqual({r.direction for r in _find_active_bookings_for_container(C_OUT)}, {"Tank Out"})

	def test_voiding_the_outbound_a_return_is_waiting_for_is_refused(self):
		"""Tank still here, booked out and back in. Voiding the Tank Out would leave the
		Tank In live on a tank that never left — a bon off it logs a second arrival."""
		self._arrived_container(C_OUT)
		outbound = self._book(C_OUT, "Tank Out")
		inbound = self._book(C_OUT, "Tank In")
		with self.assertRaises(frappe.ValidationError) as cm:
			cancel_submitted_booking(outbound.name)
		msg = str(cm.exception)
		self.assertIn(inbound.name, msg)
		self.assertIn("Langkah selanjutnya", msg)

		# The named next step works: void the return first, then the outbound goes. (The
		# refused attempt already stepped it back to draft, so only the void is left.)
		from container_depot.container_depot.doctype.container_booking.container_booking import void_draft

		cancel_submitted_booking(inbound.name)
		void_draft(outbound.name)  # must not raise

	def test_dropping_a_tank_off_the_inbound_releases_it_despite_a_pickup(self):
		"""``Booked`` is the INBOUND reservation. A tank taken off its Tank In draft is not
		coming any more; the Tank Out that also lists it used to count as "still held" and
		left it ``Booked`` for good."""
		name = frappe.get_doc({
			"doctype": "Container", "container_no": C_IN, "container_type": "ISO Tank",
			"status": "Gate_Out", "principal": self.customer,
		}).insert(ignore_permissions=True).name
		inbound = self._book(C_IN, submit=False)
		self.assertEqual(frappe.db.get_value("Container", name, "status"), "Booked")
		self._book(C_IN, "Tank Out")
		inbound.reload()
		inbound.items[0].container = None
		inbound.items[0].container_no = C_OUT
		inbound.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", name, "status"), "Gate_Out")

	def test_voiding_the_inbound_a_pickup_is_waiting_for_is_refused(self):
		inbound = self._book(C_IN)
		outbound = self._book(C_IN, "Tank Out")
		with self.assertRaises(frappe.ValidationError) as cm:
			cancel_submitted_booking(inbound.name)
		self.assertIn(outbound.name, str(cm.exception))

		from container_depot.container_depot.doctype.container_booking.container_booking import void_draft

		cancel_submitted_booking(outbound.name)
		void_draft(inbound.name)  # must not raise
		# Born for the inbound booking, so voiding it drops the phantom master outright.
		self.assertFalse(frappe.db.exists("Container", C_IN))


class TestRefusalListed(FrappeTestCase):
	"""Several tanks refused for one reason: the sentence once, the tanks listed under it."""

	def test_same_reason_is_said_once(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import _listed

		self.assertEqual(
			_listed([("Terikat BKG-1:", "AAAU1"), ("Tidak di depo:", "BBBU2"), ("Terikat BKG-1:", "CCCU3")]),
			"Terikat BKG-1:<ul><li><b>AAAU1</b></li><li><b>CCCU3</b></li></ul>"
			"Tidak di depo:<ul><li><b>BBBU2</b></li></ul>",
		)
