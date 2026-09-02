"""Gate Out Plan — customer lift-on (gate-out) notice → prep priority.

Covers the whole point of the feature:
- stamping ``target_lift_on`` / ``gate_out_plan`` onto each listed Container while Open,
  and releasing it on Fulfilled / Cancelled / row-removal / delete (without clobbering a
  stamp another plan owns);
- the work still holding each tank, answered live when a booking is picked;
- the denormalised target pushed onto already-open orders so the worklists sort by it;
- the Email → Order bridge exposing a "Gate Out" prefill.

The controller writes to the Container via ``db.set_value`` (no commit); FrappeTestCase
rolls back, and tearDown also deletes explicitly to be safe.
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from container_depot.container_depot import cleaning
from container_depot.container_depot.doctype.gate_out_plan import gate_out_plan
from container_depot.container_depot.mail_to_order import get_order_prefill
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_container

_DEPOT = "OAK1"


class TestGateOutPlan(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._principal = ensure_test_customer("GOP Test Principal")
		self._containers = []
		self._plans = []
		self._orders = []       # Cleaning Order names
		self._repairs = []      # Repair Order names
		self._eirs = []         # Inspection (EIR) names
		self._comms = []
		self._files = []        # uploaded .xlsx probes
		self._customers = []    # extra Customers minted by a test
		self._bookings = []     # Container Bookings raised to test the tracking list
		self._bons = []         # Order Bongkar bons raised to test the tracking list

	def tearDown(self):
		# frappe.response is process-global; the template download test leaves it set.
		frappe.response.clear()
		for f in self._files:
			frappe.delete_doc("File", f, force=True, ignore_permissions=True)
		for p in self._plans:
			frappe.db.delete("Gate Out Plan Item", {"parent": p})
			frappe.db.delete("Gate Out Plan", {"name": p})
		for o in self._orders:
			frappe.db.delete("Cleaning Order", {"name": o})
		for r in self._repairs:
			frappe.db.delete("Repair Order", {"name": r})
		for e in self._eirs:
			frappe.db.delete("Inspection", {"name": e})
		for b in self._bookings:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Booking Code", {"booking": b})
			frappe.db.delete("Container Booking", {"name": b})
		for b in self._bons:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Order Bongkar", {"name": b})
		for cm in self._comms:
			frappe.db.delete("Communication", {"name": cm})
		for c in self._containers:
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Repair Order", {"container": c})
			frappe.db.delete("Inspection", {"container": c})
			frappe.db.delete("Container Position Survey", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		for cust in self._customers:
			frappe.db.delete("Customer", {"name": cust})
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno, **kw):
		kw.setdefault("principal", self._principal)
		kw.setdefault("depot", _DEPOT)
		c = _make_container(cno, **kw)
		self._containers.append(c)
		return c

	def _plan(self, rows, *, status="Open", **kw):
		"""rows = list of (container, target_date)."""
		doc = frappe.get_doc({
			"doctype": "Gate Out Plan",
			"principal": kw.pop("principal", self._principal),
			"source": "Email",
			"status": status,
			"containers": [{"container": c, "target_lift_on": d} for c, d in rows],
			**kw,
		}).insert(ignore_permissions=True)
		self._plans.append(doc.name)
		return doc

	def _cleaning(self, container, status="Pending"):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": status,
		}).insert(ignore_permissions=True)
		self._orders.append(co.name)
		return co.name

	def _repair(self, container, status="Draft"):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": status,
		}).insert(ignore_permissions=True)
		self._repairs.append(ro.name)
		return ro.name

	def _booking(self, container, booking_status="Draft", direction="Tank Out", submitted=False):
		"""Validation is bypassed: pricing, contract and the payment gate say nothing about
		whether the booking shows up on this tank's tracking list."""
		doc = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": direction,
			"customer": self._principal,
			"principal": self._principal,
			"booking_status": booking_status,
			"items": [{"container": container}],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		if submitted:
			frappe.db.set_value("Container Booking", doc.name, "docstatus", 1, update_modified=False)
		self._bookings.append(doc.name)
		return doc.name

	def _bongkar(self, container, order_status="Issued"):
		"""A submitted unloading bon. Validation is bypassed — the bon's own paperwork says
		nothing about whether it shows up on this tank's tracking list."""
		doc = frappe.get_doc({
			"doctype": "Order Bongkar",
			"shipper": self._principal,
			"ex_vessel": "MV GOP TEST",
			"order_status": order_status,
			"containers": [{"container": container}],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.set_value("Order Bongkar", doc.name, "docstatus", 1, update_modified=False)
		self._bons.append(doc.name)
		return doc.name

	def _eir(self, container, inspection_type, status="Submitted"):
		"""A submitted EIR is stamped submitted, not merely labelled so.

		``docstatus`` is what the rest of the app reads — ``container_open_orders`` calls a
		draft EIR-In open work holding the tank — so an Inspection carrying status
		"Submitted" on docstatus 0 is a fixture that does not exist in the yard, and every
		readiness assertion written against it would be measuring a state the app never
		produces. Stamped directly rather than via ``submit()``: the real submit runs the
		gate (EIR-In brings the tank In_Depot, EIR-Out sends it out), which is a different
		test's subject.
		"""
		insp = frappe.get_doc({
			"doctype": "Inspection",
			"inspection_type": inspection_type,
			"container": container,
			"depot": _DEPOT,
			"eir_date": today(),
			"inspector": "Administrator",
			"status": status,
		}).insert(ignore_permissions=True)
		if status == "Submitted":
			frappe.db.set_value("Inspection", insp.name, "docstatus", 1, update_modified=False)
		self._eirs.append(insp.name)
		return insp.name

	def _target(self, container):
		return frappe.db.get_value("Container", container, ["target_lift_on", "gate_out_plan"], as_dict=True)

	# --- stamping -------------------------------------------------------------
	def test_open_plan_stamps_container(self):
		c = self._container("GOPSTAMP001")
		d = add_days(today(), 5)
		plan = self._plan([(c, d)])
		got = self._target(c)
		self.assertEqual(str(got.target_lift_on), str(d))
		self.assertEqual(got.gate_out_plan, plan.name)

	def test_fulfilled_releases_stamp(self):
		c = self._container("GOPFULL0001")
		plan = self._plan([(c, add_days(today(), 5))])
		plan.status = "Fulfilled"
		plan.save(ignore_permissions=True)
		got = self._target(c)
		self.assertIsNone(got.target_lift_on)
		self.assertIsNone(got.gate_out_plan)

	def test_delete_releases_stamp(self):
		c = self._container("GOPDEL00001")
		plan = self._plan([(c, add_days(today(), 5))])
		frappe.delete_doc("Gate Out Plan", plan.name, ignore_permissions=True, force=True)
		self._plans.remove(plan.name)
		self.assertIsNone(self._target(c).target_lift_on)

	def test_dropping_a_row_releases_that_container(self):
		a = self._container("GOPDROP001A")
		b = self._container("GOPDROP001B")
		d = add_days(today(), 4)
		plan = self._plan([(a, d), (b, d)])
		self.assertEqual(str(self._target(a).target_lift_on), str(d))
		# Remove B's row, keep A.
		plan.set("containers", [r for r in plan.containers if r.container == a])
		plan.save(ignore_permissions=True)
		self.assertEqual(str(self._target(a).target_lift_on), str(d))
		self.assertIsNone(self._target(b).target_lift_on)

	# --- one active plan per container ---------------------------------------
	def test_container_blocked_in_second_open_plan(self):
		c = self._container("GOPUNIQ001")
		self._plan([(c, add_days(today(), 3))])  # plan 1 (Open) claims the tank
		with self.assertRaises(frappe.ValidationError):
			self._plan([(c, add_days(today(), 5))])  # plan 2 (Open) may not reuse it

	def test_duplicate_container_in_same_plan_blocked(self):
		c = self._container("GOPUNIQ002")
		d = add_days(today(), 4)
		with self.assertRaises(frappe.ValidationError):
			self._plan([(c, d), (c, d)])  # same tank listed twice in one plan

	def test_closing_a_plan_frees_the_container(self):
		c = self._container("GOPUNIQ003")
		p1 = self._plan([(c, add_days(today(), 3))])
		p1.status = "Fulfilled"
		p1.save(ignore_permissions=True)  # released — no longer an active claim
		p2 = self._plan([(c, add_days(today(), 6))])  # now allowed to claim it
		self.assertEqual(self._target(c).gate_out_plan, p2.name)

	# --- what still holds a tank (the picker's answer) -------------------------
	def test_picker_names_the_work_holding_a_tank(self):
		"""The plan no longer stores a Kesiapan column — the question is asked live, at the
		one moment it matters: when the operator picks tanks for a booking.

		A draft EIR-In counts. The plan's old lookup saw only Cleaning / M&R, so the thing
		most likely to be holding a tank that just arrived read as ready.
		"""
		c = self._container("GOPRDY0005")
		self._eir(c, "EIR-In", status="Draft")
		plan = self._plan([(c, add_days(today(), 5))])

		row = gate_out_plan.pickable_containers(plan.name)[0]
		self.assertEqual(row["blockers"], ["EIR-In"])
		self.assertFalse(row["ready"])

	def test_picker_does_not_offer_a_tank_that_has_not_arrived(self):
		"""Nothing is open on a tank that was never here — which is exactly why "no open
		work" was the wrong test on its own. Presence is asked first."""
		coming = self._container("GOPRDY0007", status="Booked")
		here = self._container("GOPRDY0006", status="Available")
		plan = self._plan([(coming, add_days(today(), 3)), (here, add_days(today(), 2))])

		ready = {r["container"]: r["ready"] for r in gate_out_plan.pickable_containers(plan.name)}
		self.assertEqual(ready, {coming: False, here: True})

	def test_related_orders_names_the_blockers_per_container(self):
		"""The detail list has to name WHICH order holds a tank up, and agree with the column:
		exactly the orders whose ``blocks`` is true are the ones behind "Belum"."""
		c = self._container("GOPREL0001")
		co = self._cleaning(c, status="Completed")
		ro = self._repair(c)
		plan = self._plan([(c, add_days(today(), 5))])

		tanks = gate_out_plan.related_orders(plan.name)
		self.assertEqual(len(tanks), 1)
		by_name = {o["name"]: o for o in tanks[0]["orders"]}
		self.assertFalse(by_name[co]["blocks"])   # finished cleaning is history
		self.assertTrue(by_name[ro]["blocks"])    # the open M&R is the blocker
		self.assertEqual(by_name[ro]["kind"], "M&R")
		# ...and the picker names the same order as what is holding the tank.
		self.assertEqual(gate_out_plan.pickable_containers(plan.name)[0]["blockers"], ["M&R"])

	def test_import_matches_a_dashed_master_instead_of_minting_a_twin(self):
		"""The number in the file and the number in the master rarely agree on separators.

		Flattening the file value and then looking THAT up finds nothing, so `create_missing`
		registers a second master for a tank that already exists — a phantom with no depot,
		no history and a default `Gate_Out` status, which then reads as "already collected"
		on the plan. Match on the flattened form; store the number as written.
		"""
		dashed = self._container("GOP-XLS-01")
		url = self._xlsx([
			["Container", "Target Lift-On"],
			["gop xls 01", add_days(today(), 5)],   # same tank, spelled loosely
		])
		res = gate_out_plan.parse_container_xlsx(
			url, principal=self._principal, create_missing=1
		)

		self.assertEqual(res["created"], [])
		self.assertEqual([r["container"] for r in res["rows"]], [dashed])

	def test_related_orders_tracks_the_booking_and_bons_too(self):
		"""Every unfinished document against the tank, not only the work: the booking that
		authorises the visit and the bons that run it belong on the same list."""
		c = self._container("GOPREL0002")
		booking = self._booking(c, booking_status="Draft")
		cancelled = self._booking(c, booking_status="Cancelled")
		plan = self._plan([(c, add_days(today(), 5))])

		by_name = {o["name"]: o for o in gate_out_plan.related_orders(plan.name)[0]["orders"]}
		self.assertEqual(by_name[booking]["kind"], "Booking")
		self.assertTrue(by_name[booking]["open"])
		# Only the newest booking is shown per tank, so the line has to say which way that
		# one was going — "the last booking" is useless without In or Out.
		self.assertEqual(by_name[booking]["detail"], "Tank Out")
		# Paperwork is tracked, never a blocker: a Tank Out booking IS the way out, so
		# counting it as an obstacle would hold every planned tank up forever.
		self.assertFalse(by_name[booking]["blocks"])
		# A voided booking is history — neither unfinished work nor a clearance.
		self.assertTrue(by_name[cancelled]["cancelled"])
		self.assertFalse(by_name[cancelled]["open"])

	def test_related_orders_flags_a_booking_whose_bon_is_not_out_yet(self):
		"""A confirmed booking is not yet paper at the gate — say so on the line.

		The bon is what the driver is handed, and it comes off the booking one or two tanks
		at a time. A tank whose Booking Code is still Active is one nobody has issued for,
		and that is invisible from the booking's own status.
		"""
		c = self._container("GOPBON0001")
		booking = self._booking(c, booking_status="Confirmed", submitted=True)
		code = frappe.get_doc({
			"doctype": "Booking Code",
			"code": "OAK-GOPBONTEST1",
			"booking": booking,
			"direction": "Tank Out",
			"container": c,
			"container_no": "GOPBON0001",
			"state": "Active",
		}).insert(ignore_permissions=True)
		plan = self._plan([(c, add_days(today(), 5))])

		line = {o["name"]: o for o in gate_out_plan.related_orders(plan.name)[0]["orders"]}[booking]
		self.assertEqual(line["detail"], "Tank Out · belum ada bon")

		# Once the bon takes the code, the line goes back to plain direction.
		frappe.db.set_value("Booking Code", code.name, "state", "Used", update_modified=False)
		line = {o["name"]: o for o in gate_out_plan.related_orders(plan.name)[0]["orders"]}[booking]
		self.assertEqual(line["detail"], "Tank Out")

	def test_a_confirmed_tank_in_is_still_open_until_the_tank_arrives(self):
		"""Confirmed is where a booking STARTS being work, not where it stops.

		A Tank In that is approved and paid for but whose tank is still merely ``Booked`` has
		brought nothing in — the bon has not even been generated. Reading Confirmed as
		"finished" hid precisely the bookings an operator preparing a lift-on is looking for.
		"""
		waiting = self._container("GOPBKG0001", status="Booked", depot=None)
		arrived = self._container("GOPBKG0002", status="Available")
		booking_waiting = self._booking(
			waiting, booking_status="Confirmed", direction="Tank In", submitted=True
		)
		booking_arrived = self._booking(
			arrived, booking_status="Confirmed", direction="Tank In", submitted=True
		)
		plan = self._plan([
			(waiting, add_days(today(), 5)),
			(arrived, add_days(today(), 5)),
		])

		tanks = {t["container"]: t for t in gate_out_plan.related_orders(plan.name)}
		still_open = {o["name"]: o for o in tanks[waiting]["orders"]}
		self.assertTrue(still_open[booking_waiting]["open"])
		self.assertEqual(tanks[waiting]["open_count"], 1)
		# The same booking IS finished for a tank that actually turned up — judged per tank,
		# because one booking routinely covers ten of them at different stages.
		finished = {o["name"]: o for o in tanks[arrived]["orders"]}
		self.assertFalse(finished[booking_arrived]["open"])
		self.assertEqual(tanks[arrived]["open_count"], 0)

	def test_an_issued_bon_is_done_once_its_tank_has_moved(self):
		"""An Order Bongkar has no auto-complete — nothing ever advances it past ``Issued``.

		Judged by that field alone it stays "unfinished" forever, long after every tank on it
		has been unloaded and parked, which drains the meaning out of the unfinished colour.
		The tank moving is what finishes it, exactly as for the booking above.
		"""
		arrived = self._container("GOPBON0001", status="Available")
		waiting = self._container("GOPBON0002", status="Booked", depot=None)
		held = self._container("GOPBON0003", status="Available")
		done_bon = self._bongkar(arrived)
		open_bon = self._bongkar(waiting)
		held_bon = self._bongkar(held, order_status="Hold")
		plan = self._plan([
			(arrived, add_days(today(), 5)),
			(waiting, add_days(today(), 5)),
			(held, add_days(today(), 5)),
		])

		tanks = {t["container"]: t for t in gate_out_plan.related_orders(plan.name)}
		by = lambda c: {o["name"]: o for o in tanks[c]["orders"]}
		self.assertFalse(by(arrived)[done_bon]["open"])       # tank is in — the bon is spent
		self.assertTrue(by(waiting)[open_bon]["open"])        # nothing unloaded yet
		# Hold is a flag that something needs attention, so it stays open whatever the tank did.
		self.assertTrue(by(held)[held_bon]["open"])

	def test_related_orders_counts_open_and_blocking_separately(self):
		"""Unfinished and in-the-way are different questions, and the counts must not merge
		them — otherwise a draft booking reads like a tank that cannot leave."""
		c = self._container("GOPREL0003")
		self._repair(c)                       # open work: unfinished AND blocking
		self._booking(c, booking_status="Draft")   # unfinished, not blocking
		self._cleaning(c, status="Completed")      # finished: neither
		plan = self._plan([(c, add_days(today(), 5))])

		tank = gate_out_plan.related_orders(plan.name)[0]
		self.assertEqual(tank["open_count"], 2)
		self.assertEqual(tank["blocking_count"], 1)

	def test_related_orders_lists_the_eirs_without_blocking(self):
		"""The tank's EIR-In / EIR-Out belong in the list as condition history, but never as
		blockers: an EIR-Out is written AT the gate on the way out, so counting EIRs as
		prerequisites would leave every tank reading "Belum" right up to the moment it leaves."""
		c = self._container("GOPEIR0001")
		ein = self._eir(c, "EIR-In")
		eout = self._eir(c, "EIR-Out", status="Draft")
		plan = self._plan([(c, add_days(today(), 5))])

		by_name = {o["name"]: o for o in gate_out_plan.related_orders(plan.name)[0]["orders"]}
		self.assertEqual(by_name[ein]["kind"], "EIR-In")
		self.assertEqual(by_name[eout]["kind"], "EIR-Out")
		self.assertFalse(by_name[ein]["blocks"])
		self.assertFalse(by_name[eout]["blocks"])
		self.assertTrue(by_name[ein]["done"])       # submitted = a finished record
		self.assertFalse(by_name[eout]["done"])     # a draft is neither blocking nor finished
		# The EIR-In is finished and the EIR-Out is written at the gate on the way out, so
		# neither holds the tank back.
		self.assertEqual(gate_out_plan.pickable_containers(plan.name)[0]["blockers"], [])

	def test_next_lift_on_is_earliest(self):
		a = self._container("GOPNEXT001A")
		b = self._container("GOPNEXT001B")
		plan = self._plan([(a, add_days(today(), 9)), (b, add_days(today(), 2))])
		self.assertEqual(str(plan.next_lift_on), str(add_days(today(), 2)))

	# --- denormalisation onto open orders -------------------------------------
	def test_push_target_onto_open_cleaning_order(self):
		c = self._container("GOPPUSH001")
		co = self._cleaning(c)
		d = add_days(today(), 3)
		plan = self._plan([(c, d)])
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_lift_on")), str(d))
		# Closing the plan clears the denormalised copy too.
		plan.status = "Fulfilled"
		plan.save(ignore_permissions=True)
		self.assertIsNone(frappe.db.get_value("Cleaning Order", co, "target_lift_on"))

	def test_push_target_onto_open_eir(self):
		"""A draft EIR-In is open work holding the tank, so it carries the stamp too.

		The mirror used to name Cleaning and M&R itself and skipped the EIR entirely — which
		meant a tank whose ONLY open work was its arrival inspection got no urgency anywhere,
		even while the plan's own readiness column reported "Belum: EIR-In".
		"""
		c = self._container("GOPEIRPUSH1")
		eir = self._eir(c, "EIR-In", status="Draft")
		d = add_days(today(), 3)
		plan = self._plan([(c, d)])
		self.assertEqual(str(frappe.db.get_value("Inspection", eir, "target_lift_on")), str(d))
		# Closing the plan releases the EIR's copy exactly like the other orders'.
		plan.status = "Fulfilled"
		plan.save(ignore_permissions=True)
		self.assertIsNone(frappe.db.get_value("Inspection", eir, "target_lift_on"))

	def test_push_target_onto_open_eir_out(self):
		"""EIR-Out is NOT a blocker (container_open_orders leaves it out on purpose) but it
		is still unfinished work on a tank the customer is coming for, and its worklist is
		the one place where "the pickup is today" matters most."""
		c = self._container("GOPEIRPUSH2")
		eir = self._eir(c, "EIR-Out", status="Draft")
		d = add_days(today(), 2)
		self._plan([(c, d)])
		self.assertEqual(str(frappe.db.get_value("Inspection", eir, "target_lift_on")), str(d))

	def test_push_target_onto_open_position_survey(self):
		"""Same reasoning as the EIR-Out one line up: locating the tank is part of getting it
		OUT, so the survey never appears in ``container_open_orders`` — and its worklist is
		the one that wants the date most. A surveyor with ten tanks to find should walk to the
		one on a truck's schedule first."""
		c = self._container("GOPCPSPUSH1")
		survey = frappe.get_doc({
			"doctype": "Container Position Survey", "container": c,
			"depot": frappe.db.get_value("Container", c, "depot"), "status": "Pending Survey",
		}).insert(ignore_permissions=True).name
		d = add_days(today(), 2)
		plan = self._plan([(c, d)])
		self.assertEqual(
			str(frappe.db.get_value("Container Position Survey", survey, "target_lift_on")), str(d)
		)
		# Closing the plan releases the survey's copy exactly like every other order's.
		plan.status = "Fulfilled"
		plan.save(ignore_permissions=True)
		self.assertIsNone(frappe.db.get_value("Container Position Survey", survey, "target_lift_on"))

	def test_submitted_eir_keeps_no_target(self):
		"""Finished work is not prioritised — the stamp reaches OPEN orders only."""
		c = self._container("GOPEIRDONE1")
		eir = self._eir(c, "EIR-In", status="Submitted")
		self._plan([(c, add_days(today(), 3))])
		self.assertIsNone(frappe.db.get_value("Inspection", eir, "target_lift_on"))

	def test_eir_worklist_sorts_nearest_target_first(self):
		"""Same priority rule as the cleaning / M&R worklists, so one habit covers all three."""
		from container_depot.container_depot import eir as eir_api

		near = self._container("GOPEIRSRT0N")
		far = self._container("GOPEIRSRT0F")
		self._eir(far, "EIR-In", status="Draft")    # unstamped → sinks
		self._eir(near, "EIR-In", status="Draft")
		self._plan([(near, add_days(today(), 1))])
		nos = [i["container_no"] for i in eir_api.list_pending_eirs(page_length=50)["items"]]
		self.assertLess(nos.index("GOPEIRSRT0N"), nos.index("GOPEIRSRT0F"))

	def test_new_order_inherits_target_via_fetch_from(self):
		c = self._container("GOPFETCH001")
		d = add_days(today(), 6)
		self._plan([(c, d)])
		# An order created AFTER the container is stamped inherits it via fetch_from.
		co = self._cleaning(c)
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_lift_on")), str(d))

	def test_worklist_sorts_nearest_target_first(self):
		near = self._container("GOPSORT00NR")
		far = self._container("GOPSORT00FR")
		co_far = self._cleaning(far)     # unstamped → should sink
		co_near = self._cleaning(near)
		self._plan([(near, add_days(today(), 1))])
		items = cleaning.list_open_cleaning_orders(page_length=0)["items"]
		names = [i["name"] for i in items]
		self.assertIn(co_near, names)
		self.assertIn(co_far, names)
		self.assertLess(names.index(co_near), names.index(co_far))

	# --- % Keluar / auto-close ------------------------------------------------
	def _gate_out(self, container):
		"""Send a listed tank out the way the depot does: submitting a clean EIR-Out IS the
		departure (``Inspection.on_submit`` runs the gate-out)."""
		frappe.db.set_value("Container", container, "status", "Available", update_modified=False)
		eir = frappe.new_doc("Inspection")
		eir.inspection_type = "EIR-Out"
		eir.container = container
		eir.inspector = frappe.session.user
		eir.insert(ignore_permissions=True)
		eir.submit()
		frappe.db.delete("Inspection", {"container": container})

	def _plan_row(self, plan):
		return frappe.db.get_value("Gate Out Plan", plan, ["status", "per_fulfilled"], as_dict=True)

	def test_per_fulfilled_starts_at_zero(self):
		c = self._container("GOPPCT00001")
		plan = self._plan([(c, add_days(today(), 3))])
		self.assertEqual(plan.per_fulfilled, 0)

	def test_partial_gate_out_moves_the_percentage_without_closing(self):
		a = self._container("GOPPCT00002")
		b = self._container("GOPPCT00003")
		plan = self._plan([(a, add_days(today(), 3)), (b, add_days(today(), 3))])
		self._gate_out(a)

		row = self._plan_row(plan.name)
		self.assertEqual(row.per_fulfilled, 50)
		self.assertEqual(row.status, "Open")
		# Still Open, so the tank that has NOT left keeps its priority stamp.
		self.assertIsNotNone(self._target(b).target_lift_on)

	def test_last_tank_out_fulfils_the_plan_and_releases_the_stamps(self):
		a = self._container("GOPPCT00004")
		b = self._container("GOPPCT00005")
		plan = self._plan([(a, add_days(today(), 3)), (b, add_days(today(), 3))])
		self._gate_out(a)
		self._gate_out(b)

		row = self._plan_row(plan.name)
		self.assertEqual(row.per_fulfilled, 100)
		self.assertEqual(row.status, "Fulfilled")
		for c in (a, b):
			got = self._target(c)
			self.assertIsNone(got.target_lift_on)
			self.assertIsNone(got.gate_out_plan)

	def test_fulfilled_plan_frees_the_tank_for_the_next_notice(self):
		"""The reason auto-close matters: an Open plan blocks the tank's next lift-on notice."""
		c = self._container("GOPPCT00006")
		self._plan([(c, add_days(today(), 3))])
		self._gate_out(c)
		# Tank comes back in and the customer announces the next lift-on.
		frappe.db.set_value("Container", c, "status", "Available", update_modified=False)
		nxt = self._plan([(c, add_days(today(), 20))])  # would throw while the old plan is Open
		self.assertEqual(nxt.status, "Open")

	def test_rows_carry_a_gated_out_flag(self):
		c = self._container("GOPPCT00007")
		plan = self._plan([(c, add_days(today(), 3))])
		self.assertEqual(plan.containers[0].gated_out, 0)
		self._gate_out(c)
		self.assertEqual(
			frappe.db.get_value("Gate Out Plan Item", plan.containers[0].name, "gated_out"), 1
		)

	def test_a_tank_already_out_when_listed_does_not_count_as_collected(self):
		"""``Gate_Out`` also means "never was here" — the default a bulk-imported master
		carries until it gates in. Reading it flat made a plan 100% collected on the day it
		was written: no booking to raise, and an auto-close that never fires."""
		c = self._container("GOPPCT00008", depot=None, status="Gate_Out")
		plan = self._plan([(c, add_days(today(), 3))])
		self.assertEqual(plan.containers[0].gated_out, 0)
		self.assertEqual(plan.containers[0].was_out, 1)
		self.assertEqual(plan.per_fulfilled, 0)

	def test_a_tank_that_comes_back_and_leaves_again_counts(self):
		"""The baseline is spent the moment the tank is in the yard again — otherwise a
		notice for a tank the customer returns could never be fulfilled."""
		c = self._container("GOPPCT00009", depot=None, status="Gate_Out")
		plan = self._plan([(c, add_days(today(), 3))])
		self.assertEqual(plan.containers[0].was_out, 1)

		# Back in the yard: the baseline clears on the next save.
		frappe.db.set_value("Container", c, "status", "In_Depot", update_modified=False)
		plan.save(ignore_permissions=True)
		self.assertEqual(plan.containers[0].was_out, 0)

		self._gate_out(c)
		self.assertEqual(self._plan_row(plan.name).per_fulfilled, 100)

	# --- email bridge ---------------------------------------------------------
	def test_email_prefill_maps_to_gate_out_plan(self):
		comm = frappe.get_doc({
			"doctype": "Communication", "communication_type": "Communication",
			"communication_medium": "Email", "sent_or_received": "Received",
			"subject": "Lift on next week", "content": "Tolong siapkan tank kami.",
			"sender": "ops@example.com",
		}).insert(ignore_permissions=True)
		self._comms.append(comm.name)
		res = get_order_prefill(comm.name, "Gate Out")
		self.assertEqual(res["doctype"], "Gate Out Plan")
		self.assertEqual(res["values"]["reff_email"], comm.name)
		self.assertIn("notes", res["values"])

	# --- Excel import ---------------------------------------------------------
	def _xlsx(self, rows):
		"""An .xlsx attachment holding ``rows`` — the shape the grid importer reads."""
		import xlsxwriter

		buf = io.BytesIO()
		wb = xlsxwriter.Workbook(buf, {"in_memory": True})
		ws = wb.add_worksheet()
		for r, cells in enumerate(rows):
			ws.write_row(r, 0, cells)
		wb.close()
		f = frappe.get_doc({
			"doctype": "File",
			"file_name": "gop-import-probe.xlsx",
			"is_private": 1,
			"content": buf.getvalue(),
		}).insert(ignore_permissions=True)
		self._files.append(f.name)
		return f.file_url

	def test_import_resolves_dates_and_dedupes(self):
		c1 = self._container("GOPXLS00001")
		c2 = self._container("GOPXLS00002")
		when = add_days(today(), 6)
		url = self._xlsx([
			["Container", "Target Lift-On", "Catatan"],   # header, skipped
			["gopxls00001", when, "buru-buru"],           # lower case -> normalised
			["GOPXLS-00001", when, ""],                   # same tank, punctuated -> collapsed
			["GOPXLS00002", when, ""],
		])
		res = gate_out_plan.parse_container_xlsx(url, principal=self._principal)

		self.assertEqual([r["container"] for r in res["rows"]], [c1, c2])
		self.assertEqual(res["rows"][0]["target_lift_on"], str(when))
		self.assertEqual(res["rows"][0]["remark"], "buru-buru")
		self.assertEqual(res["unknown"], [])

	def test_import_skips_unknown_and_foreign_tanks(self):
		mine = self._container("GOPXLS00003")
		other = ensure_test_customer("GOP Other Principal")
		self._customers.append(other)
		theirs = self._container("GOPXLS00004", principal=other)
		url = self._xlsx([
			["Container", "Target Lift-On"],
			["GOPXLS00003", add_days(today(), 4)],
			["GOPXLS00004", add_days(today(), 4)],   # another owner's tank
			["NOSUCH1234567", add_days(today(), 4)], # not in the Container master
		])
		res = gate_out_plan.parse_container_xlsx(url, principal=self._principal)

		self.assertEqual([r["container"] for r in res["rows"]], [mine])
		self.assertEqual(res["unknown"], ["NOSUCH1234567"])
		self.assertTrue(any(theirs in e or "GOPXLS00004" in e for e in res["errors"]))

	def test_import_registers_missing_tanks_when_asked(self):
		# The depot routinely holds tanks whose master entry lags the yard; with the option
		# on, the notice is transcribed in one go and the new masters are named back.
		known = self._container("GOPXLS00006")
		url = self._xlsx([
			["Container", "Target Lift-On"],
			["GOPXLS00006", add_days(today(), 5)],
			["gopxls-00007", add_days(today(), 5)],  # not in the master yet
		])
		res = gate_out_plan.parse_container_xlsx(
			url, principal=self._principal, create_missing=1
		)

		self.assertEqual(res["unknown"], [])
		# Registered AS WRITTEN (tidied to upper case), separators and all. Flattening it
		# here would file the tank under a number nobody uses, and a later file spelling it
		# the original way would not recognise its own tank.
		self.assertEqual(res["created"], ["GOPXLS-00007"])
		self.assertEqual([r["is_new"] for r in res["rows"]], [0, 1])
		self.assertEqual(res["rows"][0]["container"], known)

		made = res["rows"][1]["container"]
		self._containers.append(made)
		# Owner only. No depot, and the doctype's own default status (Departed): the import
		# registers a tank the customer named, it does not invent a gate-in.
		self.assertEqual(
			frappe.db.get_value("Container", made, ["container_no", "principal", "depot", "status"]),
			("GOPXLS-00007", self._principal, None, "Gate_Out"),
		)
		# And the plan the rows land on saves — the created master matches the header, so
		# _assert_rows_match_header has nothing to complain about — carrying the badge the
		# importer set on each row through the save, exactly as the grid hands it over.
		plan = frappe.get_doc({
			"doctype": "Gate Out Plan",
			"principal": self._principal,
			"source": "Email",
			"status": "Open",
			"containers": [
				{
					"container": r["container"],
					"target_lift_on": r["target_lift_on"],
					"is_new_container": r["is_new"],
				}
				for r in res["rows"]
			],
		}).insert(ignore_permissions=True)
		self._plans.append(plan.name)
		plan.reload()
		self.assertEqual([r.is_new_container for r in plan.containers], [0, 1])

	def test_import_refuses_to_create_without_a_principal(self):
		# A Container cannot exist without an owner and this must not guess one.
		url = self._xlsx([["Container", "Target Lift-On"], ["GOPXLS00008", add_days(today(), 5)]])
		with self.assertRaises(frappe.ValidationError):
			gate_out_plan.parse_container_xlsx(url, principal=None, create_missing=1)
		self.assertFalse(frappe.db.exists("Container", {"container_no": "GOPXLS00008"}))

	def test_import_keeps_a_row_whose_date_is_missing(self):
		# Target Lift-On is mandatory on the row, so a blank cell shows up on the grid where
		# the operator can fill it — losing the container instead would be worse.
		c = self._container("GOPXLS00005")
		url = self._xlsx([["Container", "Target Lift-On"], ["GOPXLS00005", ""]])
		res = gate_out_plan.parse_container_xlsx(url, principal=self._principal)

		self.assertEqual([r["container"] for r in res["rows"]], [c])
		self.assertIsNone(res["rows"][0]["target_lift_on"])
		self.assertEqual(len(res["errors"]), 1)

	def test_import_rejects_no_file(self):
		with self.assertRaises(frappe.ValidationError):
			gate_out_plan.parse_container_xlsx(None)

	def test_template_is_a_download(self):
		gate_out_plan.download_container_template()
		self.assertEqual(frappe.response.get("type"), "download")
		self.assertEqual(frappe.response.get("filename"), "gate_out_plan_template.xlsx")
		self.assertEqual(frappe.response["filecontent"][:2], b"PK")  # xlsx = zip magic

	# --- hand-off to Container Booking (Tank Out) -----------------------------
	def test_make_booking_carries_the_plan(self):
		c = self._container("GOPBKG00001")
		when = add_days(today(), 5)
		plan = self._plan([(c, when)], customer_do_no="RDO-99", reff_doc="MAIL-7", notes="ambil pagi")

		booking = gate_out_plan.make_container_booking(plan.name)

		self.assertEqual(booking.doctype, "Container Booking")
		self.assertEqual(booking.direction, "Tank Out")
		self.assertEqual(booking.principal, self._principal)
		self.assertEqual(booking.gate_out_plan, plan.name)
		self.assertEqual(booking.do_reference, "RDO-99")
		self.assertEqual(booking.reff_doc, "MAIL-7")
		# Branch is mandatory on the booking; with every collected tank in one depot the
		# hand-off fills it from the tanks rather than from a header the plan no longer has.
		self.assertTrue(booking.branch)
		self.assertEqual(len(booking.items), 1)
		row = booking.items[0]
		self.assertEqual(row.container, c)
		# Depot rides along per row — nobody types it, and the outbound booking has no header
		# depot to read it from.
		self.assertEqual(row.depot, _DEPOT)
		# The plan's target date IS the booking line's date — not "today".
		self.assertEqual(str(row.tanggal_bongkar), str(when))
		self.assertEqual(row.condition, "EMPTY CLEAN")
		# This plan named no payer, so the booking still has to ask for one.
		self.assertFalse(booking.customer)
		# Charges are never seeded — the plan has no pricing.
		self.assertFalse(booking.charges)

	def test_make_booking_carries_the_bill_to_customer(self):
		"""The party billed for the lift-on is recorded on the plan, not assumed to be the
		tank owner — and a line with no transporter of its own falls back to it."""
		payer = ensure_test_customer("GOP Test Payer")
		self._customers.append(payer)
		c = self._container("GOPBKG00006")
		plan = self._plan([(c, add_days(today(), 4))], customer=payer)

		booking = gate_out_plan.make_container_booking(plan.name)

		self.assertEqual(booking.customer, payer)
		self.assertEqual(booking.principal, self._principal)
		self.assertEqual(booking.items[0].shipper, payer)

	def test_make_booking_carries_the_trucking_details(self):
		"""EMKL / truck / driver / RO transcribed from the customer's mail ride along, and an
		explicitly named transporter is NOT overwritten by the Bill To fallback."""
		payer = ensure_test_customer("GOP Test Payer")
		hauler = ensure_test_customer("GOP Test Hauler")
		self._customers += [payer, hauler]
		c = self._container("GOPBKG00007")
		plan = self._plan([(c, add_days(today(), 4))], customer=payer)
		plan.containers[0].update({
			"shipper": hauler,
			"truck_plate": "BK 1234 XX",
			"driver": "Budi",
			"driver_phone": "0811-2233",
			"ro": "RO-9",
		})
		plan.save(ignore_permissions=True)

		row = gate_out_plan.make_container_booking(plan.name).items[0]

		self.assertEqual(row.shipper, hauler)
		self.assertEqual(row.truck_plate, "BK 1234 XX")
		self.assertEqual(row.driver, "Budi")
		self.assertEqual(row.driver_phone, "0811-2233")
		self.assertEqual(row.ro, "RO-9")

	def test_make_booking_reads_the_condition_off_the_open_cleaning(self):
		c = self._container("GOPBKG00002")
		self._cleaning(c, status="In_Progress")
		plan = self._plan([(c, add_days(today(), 5))])

		booking = gate_out_plan.make_container_booking(plan.name)
		self.assertEqual(booking.items[0].condition, "EMPTY DIRTY")

	def test_make_booking_calls_a_tank_with_no_open_cleaning_clean(self):
		c = self._container("GOPBKG00007")
		self._cleaning(c, status="Completed")
		plan = self._plan([(c, add_days(today(), 5))])

		booking = gate_out_plan.make_container_booking(plan.name)
		self.assertEqual(booking.items[0].condition, "EMPTY CLEAN")

	def test_picker_reads_status_live_not_off_the_saved_row(self):
		"""The picker and the Order & EIR tab must never disagree about the same tank.

		The row's mirrored status is only as fresh as the last save, so a tank whose work
		finished afterwards still offered itself as In_Depot — unticked — while the tab
		already called it Available. Both now read the master.
		"""
		c = self._container("GOPLIVE0001", status="In_Depot")
		plan = self._plan([(c, add_days(today(), 3))])
		self.assertEqual(plan.containers[0].container_status, "In_Depot")

		# Work finishes; the master moves on without the plan being touched.
		frappe.db.set_value("Container", c, "status", "Available", update_modified=False)

		picked = gate_out_plan.pickable_containers(plan.name)
		self.assertEqual([r["status"] for r in picked], ["Available"])
		self.assertEqual([r["ready"] for r in picked], [True])
		# ...and the tab, its other source, says exactly the same thing.
		self.assertEqual(gate_out_plan.related_orders(plan.name)[0]["status"], "Available")

	def test_picker_drops_tanks_that_already_left(self):
		gone = self._container("GOPLIVE0002")
		staying = self._container("GOPLIVE0003")
		plan = self._plan([(gone, add_days(today(), 3)), (staying, add_days(today(), 4))])
		self._gate_out(gone)
		self.assertEqual(
			[r["container"] for r in gate_out_plan.pickable_containers(plan.name)], [staying]
		)

	def test_make_booking_takes_only_the_containers_chosen(self):
		"""A plan is collected over several visits, so the form asks which tanks THIS booking
		is for. Everything else on the plan stays behind, still claimed by the plan."""
		wanted = self._container("GOPPICK001")
		left_behind = self._container("GOPPICK002")
		plan = self._plan([
			(wanted, add_days(today(), 3)),
			(left_behind, add_days(today(), 9)),
		])

		booking = gate_out_plan.make_container_booking(plan.name, containers=[wanted])
		self.assertEqual([r.container for r in booking.items], [wanted])

		# No choice made = the whole plan, as before.
		everything = gate_out_plan.make_container_booking(plan.name)
		self.assertEqual(
			sorted(r.container for r in everything.items), sorted([wanted, left_behind])
		)

	def test_make_booking_refuses_when_every_chosen_tank_has_left(self):
		gone = self._container("GOPPICK003")
		staying = self._container("GOPPICK004")
		plan = self._plan([(gone, add_days(today(), 3)), (staying, add_days(today(), 4))])
		self._gate_out(gone)
		plan.reload()

		with self.assertRaises(frappe.ValidationError):
			gate_out_plan.make_container_booking(plan.name, containers=[gone])

	def test_make_booking_drops_tanks_that_already_left(self):
		gone = self._container("GOPBKG00003")
		staying = self._container("GOPBKG00004")
		plan = self._plan([(gone, add_days(today(), 2)), (staying, add_days(today(), 3))])
		self._gate_out(gone)

		booking = gate_out_plan.make_container_booking(plan.name)
		self.assertEqual([r.container for r in booking.items], [staying])

	def test_make_booking_refuses_a_fully_collected_plan(self):
		c = self._container("GOPBKG00005")
		plan = self._plan([(c, add_days(today(), 2))])
		self._gate_out(c)
		with self.assertRaises(frappe.ValidationError):
			gate_out_plan.make_container_booking(plan.name)

	# --- a booked tank is a commitment ----------------------------------------
	def test_cannot_cancel_a_plan_whose_tank_is_already_booked_out(self):
		"""Closing the plan releases every tank's lift-on stamp — which must not happen
		while a lift-on booking is still waiting for one of them."""
		c = self._container("GOPHOLD0001", status="Available")
		plan = self._plan([(c, add_days(today(), 3))])
		booking = self._booking(c, booking_status="Confirmed", submitted=True)

		held = gate_out_plan.blocking_bookings(plan.name)
		self.assertEqual([(h["container"], h["booking"]) for h in held], [(c, booking)])

		plan.status = "Cancelled"
		with self.assertRaises(frappe.ValidationError):
			plan.save(ignore_permissions=True)

	def test_a_cancelled_booking_no_longer_holds_the_plan(self):
		c = self._container("GOPHOLD0002", status="Available")
		plan = self._plan([(c, add_days(today(), 3))])
		booking = self._booking(c, booking_status="Confirmed", submitted=True)
		frappe.db.set_value("Container Booking", booking, "booking_status", "Cancelled")

		self.assertEqual(gate_out_plan.blocking_bookings(plan.name), [])
		plan.status = "Cancelled"
		plan.save(ignore_permissions=True)
		self.assertIsNone(self._target(c).target_lift_on)

	def test_a_tank_already_collected_does_not_hold_the_plan_open(self):
		"""Half a notice collected, the rest called off: the bookings behind the tanks that
		already left have done their job, so only the tanks still here can hold the plan."""
		gone = self._container("GOPHOLD0003", status="Available")
		staying = self._container("GOPHOLD0004", status="Available")
		plan = self._plan([(gone, add_days(today(), 2)), (staying, add_days(today(), 5))])
		self._booking(gone, booking_status="Confirmed", submitted=True)
		self._gate_out(gone)

		self.assertEqual(gate_out_plan.blocking_bookings(plan.name), [])
		plan.reload()
		plan.status = "Cancelled"
		plan.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Gate Out Plan", plan.name, "status"), "Cancelled")

	def test_a_booked_row_cannot_be_dropped_but_an_unbooked_one_can(self):
		"""The way out of a plan that is only partly going ahead: trim the tanks nobody has
		booked yet and leave the plan Open."""
		booked = self._container("GOPHOLD0005", status="Available")
		free = self._container("GOPHOLD0006", status="Available")
		plan = self._plan([(booked, add_days(today(), 2)), (free, add_days(today(), 4))])
		self._booking(booked, booking_status="Confirmed", submitted=True)

		plan.containers = [r for r in plan.containers if r.container != booked]
		with self.assertRaises(frappe.ValidationError):
			plan.save(ignore_permissions=True)

		plan.reload()
		plan.containers = [r for r in plan.containers if r.container != free]
		plan.save(ignore_permissions=True)
		self.assertEqual([r.container for r in plan.containers], [booked])
		self.assertIsNone(self._target(free).target_lift_on)

	def test_picker_names_the_booking_a_tank_is_already_on_and_does_not_pretick_it(self):
		booked = self._container("GOPHOLD0007", status="Available")
		free = self._container("GOPHOLD0008", status="Available")
		plan = self._plan([(booked, add_days(today(), 2)), (free, add_days(today(), 4))])
		booking = self._booking(booked, booking_status="Confirmed", submitted=True)

		picked = {r["container"]: r for r in gate_out_plan.pickable_containers(plan.name)}
		self.assertEqual(picked[booked]["booking"], booking)
		self.assertFalse(picked[booked]["ready"])
		# ...and the tank nobody booked is still offered, ticked.
		self.assertIsNone(picked[free]["booking"])
		self.assertTrue(picked[free]["ready"])

	# --- header vs rows -------------------------------------------------------
	def test_container_of_another_principal_is_refused(self):
		other = ensure_test_customer("GOP Other Principal")
		self._customers.append(other)
		theirs = self._container("GOPHDR00001", principal=other)
		with self.assertRaises(frappe.ValidationError):
			self._plan([(theirs, add_days(today(), 4))])
		# Refused means refused: no stamp leaked onto somebody else's tank.
		self.assertIsNone(self._target(theirs).target_lift_on)

	def test_container_anywhere_is_accepted(self):
		# A plan is a notice written days ahead, so the header Depot says where OAK expects
		# to hand the tank over — NOT where it has to be sitting today. A tank at another
		# depot, or one that has never gated in here at all, is still plannable.
		elsewhere = self._container("GOPHDR00002", depot="OAK2")
		nowhere = self._container("GOPHDR00006", depot=None, status="Gate_Out")
		plan = self._plan([
			(elsewhere, add_days(today(), 4)),
			(nowhere, add_days(today(), 5)),
		])
		self.assertEqual(len(plan.containers), 2)
		self.assertEqual(self._target(elsewhere).target_lift_on, getdate(add_days(today(), 4)))
		self.assertEqual(self._target(nowhere).target_lift_on, getdate(add_days(today(), 5)))
		# Where each tank stands is per row, read off its own master — there is no header
		# Depot to declare one answer for the whole notice.
		self.assertEqual([r.depot for r in plan.containers], ["OAK2", None])

	def test_changing_the_principal_refuses_the_old_rows(self):
		# What the Desk form prevents by clearing the table; the server says it too, because
		# saving is what stamps the target onto the tank.
		c = self._container("GOPHDR00003")
		other = ensure_test_customer("GOP Other Principal")
		self._customers.append(other)
		plan = self._plan([(c, add_days(today(), 4))])
		plan.principal = other
		with self.assertRaises(frappe.ValidationError):
			plan.save(ignore_permissions=True)

	def test_a_tank_that_already_left_is_not_re_checked(self):
		# A partly-collected plan must stay editable: where a departed tank belongs now says
		# nothing about the lift-on it was collected under.
		gone = self._container("GOPHDR00004")
		staying = self._container("GOPHDR00005")
		plan = self._plan([(gone, add_days(today(), 2)), (staying, add_days(today(), 3))])
		self._gate_out(gone)
		other = ensure_test_customer("GOP Other Principal")
		self._customers.append(other)
		frappe.db.set_value("Container", gone, "principal", other, update_modified=False)

		plan.reload()
		plan.notes = "sisa satu tank"
		plan.save(ignore_permissions=True)  # must not throw
		self.assertEqual(plan.notes, "sisa satu tank")
