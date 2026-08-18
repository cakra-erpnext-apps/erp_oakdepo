"""Gate Out Plan — customer lift-on (gate-out) notice → prep priority.

Covers the whole point of the feature:
- stamping ``target_lift_on`` / ``gate_out_plan`` onto each listed Container while Open,
  and releasing it on Fulfilled / Cancelled / row-removal / delete (without clobbering a
  stamp another plan owns);
- readiness computed from the tank's open Cleaning / M&R work;
- the denormalised target pushed onto already-open orders so the worklists sort by it;
- the Email → Order bridge exposing a "Gate Out" prefill.

The controller writes to the Container via ``db.set_value`` (no commit); FrappeTestCase
rolls back, and tearDown also deletes explicitly to be safe.
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

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
		for cm in self._comms:
			frappe.db.delete("Communication", {"name": cm})
		for c in self._containers:
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Repair Order", {"container": c})
			frappe.db.delete("Inspection", {"container": c})
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
			"depot": kw.pop("depot", _DEPOT),
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

	def _eir(self, container, inspection_type, status="Submitted"):
		insp = frappe.get_doc({
			"doctype": "Inspection",
			"inspection_type": inspection_type,
			"container": container,
			"depot": _DEPOT,
			"eir_date": today(),
			"inspector": "Administrator",
			"status": status,
		}).insert(ignore_permissions=True)
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

	# --- readiness ------------------------------------------------------------
	def test_readiness_ready_when_no_open_work(self):
		c = self._container("GOPRDY0001")
		plan = self._plan([(c, add_days(today(), 5))])
		row = plan.containers[0]
		self.assertEqual(row.readiness, "Siap")
		self.assertEqual(row.is_ready, 1)
		self.assertEqual(plan.readiness_summary, "1/1 siap")

	def test_readiness_flags_open_cleaning_and_mr(self):
		c = self._container("GOPRDY0002")
		self._cleaning(c)
		self._repair(c)
		plan = self._plan([(c, add_days(today(), 5))])
		row = plan.containers[0]
		self.assertEqual(row.is_ready, 0)
		self.assertIn("Cleaning", row.readiness)
		self.assertIn("M&R", row.readiness)
		self.assertEqual(plan.readiness_summary, "0/1 siap")

	# --- readiness stays current ----------------------------------------------
	def test_finishing_the_work_updates_the_plan_without_touching_it(self):
		"""The whole point of the monitoring: Kesiapan is stored, so it has to be pushed by the
		ORDERS. Finishing the last blocker must flip the plan to Siap with nobody re-saving it
		— that staleness is what made a plan read "Belum: Cleaning" long after cleaning was done."""
		c = self._container("GOPLIVE001")
		co = self._cleaning(c)
		ro = self._repair(c)
		plan = self._plan([(c, add_days(today(), 5))])
		self.assertEqual(plan.readiness_summary, "0/1 siap")

		# One blocker done -> the other is still named, and nothing re-saved the plan.
		frappe.get_doc("Cleaning Order", co).db_set("status", "Completed", update_modified=False)
		gate_out_plan.refresh_plans_for_order(frappe.get_doc("Cleaning Order", co))
		self.assertEqual(self._readiness(plan.name), ("0/1 siap", "Belum: M&R", 0))

		# Last blocker done -> Siap, still without opening the plan.
		mr_doc = frappe.get_doc("Repair Order", ro)
		mr_doc.status = "Cancelled"
		mr_doc.save(ignore_permissions=True)  # the real path: doc_events fires the refresh
		self.assertEqual(self._readiness(plan.name), ("1/1 siap", "Siap", 1))

	def test_closed_plan_is_left_alone(self):
		"""A Fulfilled plan is a record of how it closed, so later work must not rewrite its
		numbers — otherwise history changes every time a tank is cleaned again."""
		c = self._container("GOPCLOSED1")
		co = self._cleaning(c)
		plan = self._plan([(c, add_days(today(), 5))])
		plan.status = "Fulfilled"
		plan.save(ignore_permissions=True)
		before = self._readiness(plan.name)

		doc = frappe.get_doc("Cleaning Order", co)
		doc.status = "Completed"
		doc.save(ignore_permissions=True)
		self.assertEqual(self._readiness(plan.name), before)

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
		# ...and that is precisely what the stored column says.
		self.assertEqual(self._readiness(plan.name)[1], "Belum: M&R")

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
		# No open cleaning / M&R, so listing EIRs must leave the tank Siap.
		self.assertEqual(self._readiness(plan.name), ("1/1 siap", "Siap", 1))

	def _readiness(self, plan):
		"""(readiness_summary, row readiness, row is_ready) read fresh from the DB."""
		summary = frappe.db.get_value("Gate Out Plan", plan, "readiness_summary")
		row = frappe.get_all(
			"Gate Out Plan Item", filters={"parent": plan}, fields=["readiness", "is_ready"]
		)[0]
		return summary, row.readiness, row.is_ready

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
		"""Send a listed tank out the way the gate does (clean EIR-Out + mark_gate_out)."""
		from container_depot.container_depot.gate import mark_gate_out

		frappe.db.set_value("Container", container, "status", "Available", update_modified=False)
		eir = frappe.new_doc("Inspection")
		eir.inspection_type = "EIR-Out"
		eir.container = container
		eir.inspector = frappe.session.user
		eir.insert(ignore_permissions=True)
		eir.submit()
		res = mark_gate_out(container=container)
		frappe.db.delete("Inspection", {"container": container})
		return res

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
		res = self._gate_out(a)

		self.assertEqual(res["plans_fulfilled"], [])
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
		res = self._gate_out(b)

		self.assertEqual(res["plans_fulfilled"], [plan.name])
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
		res = gate_out_plan.parse_container_xlsx(url, principal=self._principal, depot=_DEPOT)

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
		res = gate_out_plan.parse_container_xlsx(url, principal=self._principal, depot=_DEPOT)

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
			url, principal=self._principal, depot=_DEPOT, create_missing=1
		)

		self.assertEqual(res["unknown"], [])
		self.assertEqual(res["created"], ["GOPXLS00007"])
		self.assertEqual([r["is_new"] for r in res["rows"]], [0, 1])
		self.assertEqual(res["rows"][0]["container"], known)

		made = res["rows"][1]["container"]
		self._containers.append(made)
		self.assertEqual(
			frappe.db.get_value("Container", made, ["container_no", "principal", "depot", "status"]),
			("GOPXLS00007", self._principal, _DEPOT, "Available"),
		)
		# And the plan the rows land on saves — the created master matches the header, so
		# _assert_rows_match_header has nothing to complain about — carrying the badge the
		# importer set on each row through the save, exactly as the grid hands it over.
		plan = frappe.get_doc({
			"doctype": "Gate Out Plan",
			"principal": self._principal,
			"depot": _DEPOT,
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
			gate_out_plan.parse_container_xlsx(url, principal=None, depot=_DEPOT, create_missing=1)
		self.assertFalse(frappe.db.exists("Container", {"container_no": "GOPXLS00008"}))

	def test_import_keeps_a_row_whose_date_is_missing(self):
		# Target Lift-On is mandatory on the row, so a blank cell shows up on the grid where
		# the operator can fill it — losing the container instead would be worse.
		c = self._container("GOPXLS00005")
		url = self._xlsx([["Container", "Target Lift-On"], ["GOPXLS00005", ""]])
		res = gate_out_plan.parse_container_xlsx(url, principal=self._principal, depot=_DEPOT)

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
		self.assertEqual(booking.depot, _DEPOT)
		self.assertEqual(booking.gate_out_plan, plan.name)
		self.assertEqual(booking.do_reference, "RDO-99")
		self.assertEqual(booking.reff_doc, "MAIL-7")
		self.assertTrue(booking.branch)  # from the depot, so the mandatory field is filled
		self.assertEqual(len(booking.items), 1)
		row = booking.items[0]
		self.assertEqual(row.container, c)
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

	def test_make_booking_reads_the_condition_off_the_tank(self):
		c = self._container("GOPBKG00002")
		frappe.db.set_value("Container", c, "cleaning_status", "In_Progress", update_modified=False)
		plan = self._plan([(c, add_days(today(), 5))])

		booking = gate_out_plan.make_container_booking(plan.name)
		self.assertEqual(booking.items[0].condition, "EMPTY DIRTY")

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

	# --- header vs rows -------------------------------------------------------
	def test_container_of_another_principal_is_refused(self):
		other = ensure_test_customer("GOP Other Principal")
		self._customers.append(other)
		theirs = self._container("GOPHDR00001", principal=other)
		with self.assertRaises(frappe.ValidationError):
			self._plan([(theirs, add_days(today(), 4))])
		# Refused means refused: no stamp leaked onto somebody else's tank.
		self.assertIsNone(self._target(theirs).target_lift_on)

	def test_container_at_another_depot_is_refused(self):
		elsewhere = self._container("GOPHDR00002", depot="OAK2")
		with self.assertRaises(frappe.ValidationError):
			self._plan([(elsewhere, add_days(today(), 4))])

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
