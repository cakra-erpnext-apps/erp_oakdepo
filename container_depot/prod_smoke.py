"""Real production smoke test — full TANK IN → TANK OUT lifecycle across every
Container Depot menu and option, driven through the same ESS PWA endpoints the
app uses.

Unlike the ``FrappeTestCase`` suite (rolled back per test, isolated units), this
script creates REAL, uniquely-tagged records on the live site, walks the whole
depot flow, verifies each step + option branch, then removes everything it made
— even on failure. Run it via ``bench execute``:

    # full run + auto teardown
    bench --site $SITE_NAME execute container_depot.prod_smoke.run

    # keep the data (skip teardown) to inspect it in the PWA/Desk
    bench --site $SITE_NAME execute container_depot.prod_smoke.run --kwargs "{'keep':1}"

    # sweep leftovers from an aborted run (by PRODTEST prefix), no scenario
    bench --site $SITE_NAME execute container_depot.prod_smoke.run --kwargs "{'cleanup_only':1}"

    # inventory the site's masters (read-only), useful when adapting the script
    bench --site $SITE_NAME execute container_depot.prod_smoke.probe

Safety: every created row is tagged with the ``PRODTEST`` prefix (containers,
customers, remarks) and registered for teardown; teardown also sweeps by prefix
so a crash before the registry is complete still cleans up. Ledger-bearing docs
(Sales Invoice / Payment Entry / Stock Entry) are cancelled before delete so the
GL/stock reverses. Runs as Administrator (all roles → passes the ESS guards).
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime, today

# --- tagging -----------------------------------------------------------------
# Container numbers, customers and remarks all carry this so teardown can find
# them (by exact registry AND by prefix sweep). Keep it distinctive.
CPREFIX = "PRODTEST"          # container_no / Container.name prefix
CUST_PREFIX = "PRODTEST "     # Customer.customer_name prefix (note trailing space)


def _log(msg):
	print(msg)
	frappe.logger("prod_smoke").info(msg)


def _eir_masters():
	from container_depot.operations import eir
	return eir.get_eir_masters()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
class SmokeRun:
	def __init__(self, tag=None, keep=False):
		self.tag = tag or ("PRODTEST-" + now_datetime().strftime("%Y%m%d%H%M%S"))
		self.keep = bool(keep)
		self.created: list[tuple[str, str]] = []   # (doctype, name) in creation order
		self.results: list[tuple[str, bool, str]] = []  # (label, ok, detail)
		# masters resolved in ensure_masters()
		self.company = None
		self.branch = None
		self.depot = None
		self.lift_item = None
		self.mr_item = None
		self.customer = None       # golden customer (Both contract)
		self.contract = None
		# golden-flow handles
		self.container = None      # golden container_no (== Container.name)
		self.in_booking = None
		self.out_booking = None
		self.order_bongkar = None
		self.order_muat = None
		self.cleaning_done = False

	# -- registry -----------------------------------------------------------
	def track(self, doctype, name):
		if name and (doctype, name) not in self.created:
			self.created.append((doctype, name))
		return name

	# -- step runner --------------------------------------------------------
	def step(self, label, fn, *, expect_error=None):
		"""Run one step. ``expect_error`` (a substring or True) asserts the call
		RAISES; otherwise a raise is a FAIL. Never aborts the run."""
		try:
			out = fn()
			if expect_error:
				self.results.append((label, False, "expected an error but none was raised"))
				_log(f"[FAIL] {label} — expected error, got success")
				return None
			self.results.append((label, True, ""))
			_log(f"[PASS] {label}")
			return out
		except Exception as e:
			msg = str(e).split("\n")[0][:200]
			if expect_error and (expect_error is True or expect_error in str(e)):
				self.results.append((label, True, f"raised as expected: {msg}"))
				_log(f"[PASS] {label} — blocked as expected ({msg})")
				return None
			self.results.append((label, False, msg))
			_log(f"[FAIL] {label} — {msg}")
			return None

	def assert_true(self, label, cond, detail=""):
		self.results.append((label, bool(cond), "" if cond else (detail or "assertion failed")))
		_log(("[PASS] " if cond else "[FAIL] ") + label + ("" if cond else f" — {detail}"))
		return bool(cond)

	# -- summary ------------------------------------------------------------
	def summary(self):
		passed = sum(1 for _, ok, _ in self.results if ok)
		failed = len(self.results) - passed
		_log("\n" + "=" * 60)
		_log(f"PROD SMOKE SUMMARY — {passed} passed / {failed} failed  (tag {self.tag})")
		for label, ok, detail in self.results:
			if not ok:
				_log(f"   FAIL: {label} — {detail}")
		_log("=" * 60)
		return passed, failed

	# =======================================================================
	# Masters (reuse what exists; create minimally and register for teardown)
	# =======================================================================
	def ensure_masters(self):
		self.company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
		# Branch — reuse any, else make a tagged one.
		self.branch = frappe.db.get_value("Branch", {}, "name")
		if not self.branch:
			self.branch = self.track("Branch", frappe.get_doc(
				{"doctype": "Branch", "branch": f"{self.tag} Branch"}
			).insert(ignore_permissions=True).name)
		# Depot — reuse an active one (Depot.branch is mandatory), else make one.
		self.depot = frappe.db.get_value("Depot", {"is_active": 1}, "name") or frappe.db.get_value("Depot", {}, "name")
		if not self.depot:
			self.depot = self.track("Depot", frappe.get_doc({
				"doctype": "Depot", "depot_code": "PTST", "depot_name": f"{self.tag} Depot",
				"city": "Surabaya", "branch": self.branch, "is_active": 1,
			}).insert(ignore_permissions=True).name)
		else:
			self.branch = frappe.db.get_value("Depot", self.depot, "branch") or self.branch
		# Lift item — reuse "Lift Off" (used across the suite/contracts), else make a service item.
		self.lift_item = self._ensure_service_item("Lift Off")
		# M&R used-item — a NON-STOCK service item so completion issues no stock (clean teardown).
		self.mr_item = self._pick_non_stock_item() or self.lift_item
		# Golden customer + a Both contract (Cash for Tank In, TOP for Tank Out).
		self.customer = self._ensure_customer(f"{CUST_PREFIX}{self.tag} Golden")
		self.contract = self._ensure_contract(self.customer, payment_type="Both")
		_log(f"masters: company={self.company} branch={self.branch} depot={self.depot} "
			f"lift={self.lift_item} mr_item={self.mr_item} "
			f"customer={self.customer} contract={self.contract}")

	def _ensure_service_item(self, code):
		if frappe.db.exists("Item", code):
			return code
		grp = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
		uom = frappe.db.get_value("UOM", "Nos") or frappe.db.get_value("UOM", {}, "name")
		self.track("Item", frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": code,
			"item_group": grp, "stock_uom": uom, "is_stock_item": 0, "is_sales_item": 1,
		}).insert(ignore_permissions=True).name)
		return code

	def _pick_non_stock_item(self):
		row = frappe.db.get_value("Item", {"is_stock_item": 0, "disabled": 0, "is_sales_item": 1}, "name")
		return row

	def _ensure_customer(self, name):
		hit = frappe.db.get_value("Customer", {"customer_name": name}, "name")
		if hit:
			return self.track("Customer", hit)
		grp = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
		terr = frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
		return self.track("Customer", frappe.get_doc({
			"doctype": "Customer", "customer_name": name, "customer_type": "Company",
			"customer_group": grp, "territory": terr,
		}).insert(ignore_permissions=True).name)

	def _ensure_contract(self, customer, *, payment_type):
		doc = frappe.get_doc({
			"doctype": "Depot Contract", "customer": customer, "currency": "IDR",
			"status": "Active", "payment_type": payment_type,
			"payment_terms": "NET 30" if payment_type in ("TOP", "Both") else None,
			"credit_limit": 100000000, "valid_from": today(), "valid_to": add_days(today(), 365),
			"tariff_lines": [{"item": self.lift_item, "rate": 250000}],
		}).insert(ignore_permissions=True)
		self.track("Depot Contract", doc.name)
		pl = frappe.db.get_value("Depot Contract", doc.name, "generated_price_list")
		if pl:
			self.track("Price List", pl)
		return doc.name

	# -- small helpers ------------------------------------------------------
	def _cno(self, i):
		# Container numbers must be exactly 11 chars (ISO-length check). "PRODTEST" (8) + 3 digits.
		return f"{CPREFIX}{i:03d}"

	def _damage_line(self):
		"""One real damage checklist row (item + a real damage code != 'v')."""
		m = _eir_masters()
		item = m["checklist"][0]["item_code"]
		dmg = next((d["code"] for d in m["damage_codes"] if d["code"] != "v"), m["damage_codes"][0]["code"])
		rep = next((r["code"] for r in m["repair_codes"] if r["code"] != "X"), None)
		return [{"item_code": item, "damage_code": dmg, "repair_code": rep, "remarks": "prod-smoke damage"}]

	def _pay_cash_invoice(self, si):
		"""Settle a booking's Cash Sales Invoice as the Cashier does ("mark paid"), then
		run the real bridge (:func:`sync_bookings_for_invoice`) that auto-confirms the
		booking. We settle at the DB level rather than posting a Payment Entry so the
		smoke leaves NO GL on the shared instance — the same shortcut the FrappeTestCase
		suite (``test_cash_gate``) uses. The booking auto-submit path is fully exercised."""
		from container_depot.operations.doctype.container_booking.container_booking import (
			sync_bookings_for_invoice,
		)
		frappe.db.set_value(
			"Sales Invoice", si,
			{"docstatus": 1, "status": "Paid", "outstanding_amount": 0}, update_modified=False,
		)
		self.track("Sales Invoice", si)
		sync_bookings_for_invoice(si)  # → auto-submits the paid Cash booking (Confirmed)
		return "settled"

	# =======================================================================
	# TANK IN — booking → gate-in → EIR-In → cleaning → M&R → yard → monitor
	# =======================================================================
	def tank_in(self):
		from container_depot import api
		from container_depot.ess import cleaning as ess_cleaning
		from container_depot.ess import gate as ess_gate
		from container_depot.ess import inspections as ess_eir
		from container_depot.ess import inventory as ess_inv
		from container_depot.ess import notifications as ess_notif
		from container_depot.ess import repairs as ess_mr
		from container_depot.operations import order_generation, service_menu

		self.container = self._cno(1)

		# --- 1) Booking (Cash) + Cash-unpaid gate block ---------------------
		def _mk_in_booking():
			b = frappe.get_doc({
				"doctype": "Container Booking", "direction": "Tank In",
				"customer": self.customer, "contract": self.contract,
				"payment_type": "Cash", "booking_status": "Pending Payment",
				"do_reference": f"DO-{self.tag}",
				"items": [{"container_no": self.container, "condition": "EMPTY DIRTY"}],
			}).insert(ignore_permissions=True)
			self.in_booking = b.name
			self.track("Container Booking", b.name)
			# booking resolved/created the pre-arrival container + a draft Cash SI
			frappe.db.exists("Container", self.container) and self.track("Container", self.container)
			if b.sales_invoice:
				self.track("Sales Invoice", b.sales_invoice)
			return b
		b = self.step("Booking · create Cash Tank In (draft + auto SI)", _mk_in_booking)
		if b:
			d = self.step("Booking · gate blocked while Cash unpaid",
				lambda: api._booking_gate_detail(self.in_booking))
			if d:
				self.assert_true("Booking · block_reason == cash_unpaid",
					d.get("block_reason") == "cash_unpaid" and not d.get("booking_submitted"),
					f"got {d.get('block_reason')} submitted={d.get('booking_submitted')}")

		# --- 2) Cashier pays → booking auto-submits (Confirmed) -------------
		if b and b.sales_invoice:
			self.step("Cashier · pay Cash SI → auto-submit booking",
				lambda: self._pay_cash_invoice(b.sales_invoice))
			bk = frappe.db.get_value("Container Booking", self.in_booking,
				["docstatus", "booking_status", "payment_status"], as_dict=True) or frappe._dict()
			self.assert_true("Booking · Confirmed + Paid after payment",
				bk.docstatus == 1 and bk.booking_status == "Confirmed" and bk.payment_status == "Paid",
				f"docstatus={bk.docstatus} status={bk.booking_status} pay={bk.payment_status}")

		in_code = frappe.db.get_value("Booking Code",
			{"booking": self.in_booking, "container_no": self.container}, "name")
		if in_code:
			self.track("Booking Code", in_code)
			self.assert_true("Booking · Booking Code issued (Active)",
				frappe.db.get_value("Booking Code", in_code, "state") == "Active")

		# --- 3) Gate In (ESS register_gate_entry) --------------------------
		if in_code:
			res = self.step("Gate In · register_gate_entry (ESS)",
				lambda: api.register_gate_entry(booking_code=in_code, container_no=self.container,
					truck_plate="L-1234-PT", driver_name="Pak Budi"))
			if isinstance(res, dict):
				self.assert_true("Gate In · success + container In_Depot",
					res.get("success") and frappe.db.get_value("Container", self.container, "status") == "In_Depot",
					f"res={res}")
			ge = frappe.db.get_value("Gate Entry", {"container_no": self.container}, "name")
			if ge:
				self.track("Gate Entry", ge)
				self.step("Gate In · gate_detail (ESS)", lambda: ess_gate.gate_detail(ge))
				self.step("Gate In · gate_history (ESS)", lambda: ess_gate.gate_history(search=self.container))

		# --- 4) Order Bongkar (Tank In bon) → provisions EIR-In draft -------
		if in_code:
			def _mk_bongkar():
				name = order_generation.make_order(self.in_booking, [in_code],
					vehicle_data={"ex_vessel": "MV PROD SMOKE", "shipper": self.customer}, submit=True)
				self.order_bongkar = name
				self.track("Order Bongkar", name)
				return name
			self.step("Order Bongkar · make_order + submit", _mk_bongkar)
			self.assert_true("Order Bongkar · booking code consumed (Used)",
				frappe.db.get_value("Booking Code", in_code, "state") == "Used")

		# --- 5) Order void + revert options --------------------------------
		self._exercise_order_void_and_revert()

		# --- 6) EIR-In (ESS): Empty Dirty + damage + auto-create ----------
		insp_in = None
		if self.order_bongkar:
			draft = self.step("EIR-In · open provisioned draft (ESS)",
				lambda: ess_eir.eir_open_draft(container=self.container, inspection_type="EIR-In"))
			if draft and draft.get("inspection"):
				insp_in = draft["inspection"]
				self.track("Inspection", insp_in)
				self.step("EIR-In · submit (dirty+damage, auto cleaning+M&R) (ESS)",
					lambda: ess_eir.eir_save_draft(
						inspection=insp_in, inspection_type="EIR-In", tank_status="Empty Dirty",
						referred_voucher=self.order_bongkar, create_cleaning_order=1, create_repair_order=1,
						lines=self._damage_line(), submit=1))
				self.assert_true("EIR-In · container → In_Depot",
					frappe.db.get_value("Container", self.container, "status") == "In_Depot")
				self.step("EIR-In · eir_history (ESS)", lambda: ess_eir.eir_history(search=self.container))
				self.step("EIR-In · eir_view (ESS)", lambda: ess_eir.eir_view(insp_in))

		# --- 7) Cleaning (ESS) → Completed order = the TANK OUT proof ------
		self.assert_true("Service Menu · 'Cleaning' menu is active/real",
			service_menu.is_real_menu("Cleaning"))
		co = frappe.db.get_value("Cleaning Order",
			{"container": self.container, "status": ["in", ["Pending", "In_Progress"]]}, "name")
		if co:
			self.track("Cleaning Order", co)
			self.step("Cleaning · masters (ESS)", lambda: ess_cleaning.cleaning_masters())
			self.step("Cleaning · order_detail + Service-Menu options (ESS)",
				lambda: ess_cleaning.cleaning_order_detail(co))
			self.step("Cleaning · start (ESS)", lambda: ess_cleaning.cleaning_start(co))
			self.step("Cleaning · save + submit → Completed (ESS)",
				lambda: ess_cleaning.cleaning_order_save(cleaning_order=co, cleaning_type="Steam Wash",
					remarks="prod-smoke clean", submit=1))
			done = frappe.db.exists("Cleaning Order",
				{"container": self.container, "status": "Completed", "docstatus": 1})
			self.cleaning_done = bool(done)
			self.assert_true("Cleaning · order Completed + container Available",
				bool(done) and frappe.db.get_value("Container", self.container, "status") == "Available",
				f"completed={bool(done)} status={frappe.db.get_value('Container', self.container, 'status')}")

		# --- 8) M&R (ESS): approval workflow, revision, partial approve ----
		self.assert_true("Service Menu · 'Maintenance' menu is active/real",
			service_menu.is_real_menu("Maintenance"))
		ro = frappe.db.get_value("Repair Order",
			{"container": self.container, "status": ["not in", ["Completed", "Rejected", "Cancelled"]]}, "name")
		if ro:
			self.track("Repair Order", ro)
			self.step("M&R · order_detail (damages from EIR) (ESS)", lambda: ess_mr.mr_order_detail(ro))
			self.step("M&R · items picker (Maintenance filter) (ESS)", lambda: ess_mr.mr_items(repair_order=ro))
			self.step("M&R · warehouses (ESS)", lambda: ess_mr.mr_warehouses(repair_order=ro))
			self.step("M&R · save used item (ESS)",
				lambda: ess_mr.mr_order_save(repair_order=ro,
					used_items=[{"item": self.mr_item, "quantity": 1}]))
			self.step("M&R · submit for approval (ESS)", lambda: ess_mr.mr_submit_approval(repair_order=ro))
			self.assert_true("M&R · container → In_Depot",
				frappe.db.get_value("Container", self.container, "status") == "In_Depot")
			self.step("M&R · owner requests revision (ESS)",
				lambda: ess_mr.mr_decision(repair_order=ro, decision="Revision Requested", note="tolong revisi"))
			self.step("M&R · re-edit used items (ESS)",
				lambda: ess_mr.mr_order_save(repair_order=ro, used_items=[{"item": self.mr_item, "quantity": 2}]))
			self.step("M&R · re-submit for approval (ESS)", lambda: ess_mr.mr_submit_approval(repair_order=ro))
			self.step("M&R · owner approves (partial line decision) (ESS)",
				lambda: ess_mr.mr_decision(repair_order=ro, decision="Approved",
					line_decisions={self.mr_item: "Approved"}))
			self.step("M&R · start repair (ESS)", lambda: ess_mr.mr_start(repair_order=ro))
			self.step("M&R · complete (ESS)", lambda: ess_mr.mr_order_save(repair_order=ro, submit=1))
			ro_state = frappe.db.get_value("Repair Order", ro, ["status", "stock_entry"], as_dict=True) or frappe._dict()
			self.assert_true("M&R · Completed + container Available + no stock entry",
				ro_state.status == "Completed"
				and frappe.db.get_value("Container", self.container, "status") == "Available"
				and not ro_state.stock_entry,
				f"ro={ro_state.status} stock={ro_state.stock_entry}")

		# --- 8b) M&R Reject branch (separate container) --------------------
		self._exercise_mr_reject()

		# --- 9) Monitor / Inventory (ESS) ---------------------------------
		self.step("Monitor · tank list (ESS)", lambda: ess_inv.get_tank_list(search=self.container))
		self.step("Monitor · tank detail (ESS)", lambda: ess_inv.get_tank_detail(self.container))
		self.step("Monitor · inventory summary (ESS)", lambda: ess_inv.get_inventory_summary())
		self.step("Monitor · dashboard summary (ESS)", lambda: ess_inv.get_dashboard_summary())

		# --- 11) Notifications (ESS) --------------------------------------
		nl = self.step("Notif · list (ESS)", lambda: ess_notif.list_notifications(limit=20))
		if isinstance(nl, dict) and nl.get("items"):
			first = nl["items"][0]["name"]
			self.step("Notif · mark_read (ESS)", lambda: ess_notif.mark_read(first))
		self.step("Notif · mark_all_read (ESS)", lambda: ess_notif.mark_all_read())

	def _exercise_order_void_and_revert(self):
		"""Order options: revert the golden bon to draft & re-submit, and void a throwaway bon."""
		from container_depot.operations import order_generation
		# revert + re-submit the golden Order Bongkar
		if self.order_bongkar:
			def _revert_resubmit():
				order_generation.revert_order_to_draft(self.order_bongkar, "Order Bongkar")
				doc = frappe.get_doc("Order Bongkar", self.order_bongkar)
				doc.flags.ignore_permissions = True
				doc.submit()
				return doc.name
			self.step("Order · revert-to-draft then re-submit (golden)", _revert_resubmit)
		# void a throwaway bon (own booking/container so the golden flow is untouched)
		tw_cno = self._cno(9)
		def _mk_throwaway_and_void():
			b = frappe.get_doc({
				"doctype": "Container Booking", "direction": "Tank In",
				"customer": self.customer, "contract": self.contract, "payment_type": "Cash",
				"booking_status": "Pending Payment", "do_reference": f"DO-{self.tag}-TW",
				"items": [{"container_no": tw_cno, "condition": "EMPTY CLEAN"}],
			}).insert(ignore_permissions=True)
			self.track("Container Booking", b.name)
			frappe.db.exists("Container", tw_cno) and self.track("Container", tw_cno)
			if b.sales_invoice:
				self.track("Sales Invoice", b.sales_invoice)
				self._pay_cash_invoice(b.sales_invoice)
			code = frappe.db.get_value("Booking Code", {"booking": b.name, "container_no": tw_cno}, "name")
			self.track("Booking Code", code)
			order = order_generation.make_order(b.name, [code],
				vehicle_data={"shipper": self.customer}, submit=True)
			self.track("Order Bongkar", order)
			order_generation.void_order(order, "Order Bongkar")
			return frappe.db.get_value("Order Bongkar", order, "docstatus")
		ds = self.step("Order · void throwaway bon → docstatus 2", _mk_throwaway_and_void)
		self.assert_true("Order · voided bon released its code (Active)",
			frappe.db.get_value("Booking Code", {"container_no": tw_cno}, "state") in ("Active", None))

	def _exercise_mr_reject(self):
		"""M&R Reject option on a dedicated damaged container (terminal, so isolated)."""
		from container_depot.ess import repairs as ess_mr
		from container_depot.operations import eir as eir_ops
		cno = self._cno(2)
		def _seed_damaged_container():
			frappe.get_doc({
				"doctype": "Container", "container_no": cno, "container_type": "ISO Tank",
				"status": "In_Depot", "principal": self.customer, "depot": self.depot,
			}).insert(ignore_permissions=True)
			self.track("Container", cno)
			res = eir_ops.create_eir(inspection_type="EIR-In", container=cno, tank_status="Empty Clean",
				create_repair_order=1, lines=self._damage_line(), submit=True)
			self.track("Inspection", res["name"])
			return res
		self.step("M&R Reject · seed damaged container + EIR-In (damage)", _seed_damaged_container)
		ro = frappe.db.get_value("Repair Order", {"container": cno, "status": ["!=", "Completed"]}, "name")
		if ro:
			self.track("Repair Order", ro)
			self.step("M&R Reject · add item + submit for approval",
				lambda: (ess_mr.mr_order_save(repair_order=ro, used_items=[{"item": self.mr_item, "quantity": 1}]),
					ess_mr.mr_submit_approval(repair_order=ro)))
			self.step("M&R Reject · owner rejects",
				lambda: ess_mr.mr_decision(repair_order=ro, decision="Rejected", note="tidak disetujui"))
			self.assert_true("M&R Reject · status == Rejected",
				frappe.db.get_value("Repair Order", ro, "status") == "Rejected")

	# =======================================================================
	# TANK OUT — Tank-Out booking → Release DO → Order Muat → EIR-Out → gate-out
	# =======================================================================
	def tank_out(self):
		from container_depot.ess import gate as ess_gate
		from container_depot.ess import inspections as ess_eir
		from container_depot.operations import order_generation

		if not (self.container and frappe.db.get_value("Container", self.container, "status") == "Available"
				and self.cleaning_done):
			self.assert_true("Tank Out · precondition (golden container Available + cleaned)", False,
				"golden container not Available with a finished cleaning — Tank In did not complete")
			return

		# --- 12) Tank Out booking (TOP submits freely) --------------------
		def _mk_out_booking():
			b = frappe.get_doc({
				"doctype": "Container Booking", "direction": "Tank Out",
				"customer": self.customer, "contract": self.contract, "principal": self.customer,
				"payment_type": "TOP", "booking_status": "Confirmed",
				"do_reference": f"DO-{self.tag}-OUT",
				"items": [{"container_no": self.container, "container": self.container, "condition": "EMPTY CLEAN"}],
			}).insert(ignore_permissions=True)
			self.out_booking = b.name
			self.track("Container Booking", b.name)
			b.flags.ignore_permissions = True
			b.submit()
			return b
		b = self.step("Booking · Tank Out TOP (free submit, Unpaid)", _mk_out_booking)
		if b:
			self.assert_true("Booking · Tank Out confirmed + Unpaid (TOP accrual)",
				frappe.db.get_value("Container Booking", self.out_booking, "docstatus") == 1
				and frappe.db.get_value("Container Booking", self.out_booking, "payment_status") == "Unpaid")
		out_code = frappe.db.get_value("Booking Code",
			{"booking": self.out_booking, "container_no": self.container}, "name")
		if out_code:
			self.track("Booking Code", out_code)

		# --- 13) Release DO → Available ---------------------
		def _mk_release():
			r = frappe.get_doc({
				"doctype": "Release DO", "tank_owner": self.customer, "depot": self.depot,
				"status": "Issued", "containers": [{"container": self.container, "container_no": self.container}],
			}).insert(ignore_permissions=True)
			self.track("Release DO", r.name)
			r.flags.ignore_permissions = True
			r.submit()
			return r
		self.step("Release DO · submit → Available", _mk_release)
		self.assert_true("Release DO · container Available",
			frappe.db.get_value("Container", self.container, "status") == "Available")

		# --- 14) Gate-out BLOCKED without a clean EIR-Out -----------------
		self.step("Gate Out · blocked before clean EIR-Out (ESS)",
			lambda: ess_gate.gate_out(container=self.container), expect_error=True)

		# --- 15) Order Muat (Tank Out bon) → provisions EIR-Out ----------
		if out_code:
			def _mk_muat():
				name = order_generation.make_order(self.out_booking, [out_code], vehicle_data={
					"truck_plate": "L-5678-PT", "driver_name": "Pak Muat", "driver_phone": "0811222333",
					"destination": "Pelabuhan Tanjung Perak",
				}, submit=True)
				self.order_muat = name
				self.track("Order Muat", name)
				return name
			self.step("Order Muat · make_order + submit (cleaning-gated)", _mk_muat)

		# --- 16) EIR-Out HOLD (dirty / seal broken) ----------------------
		hold_draft = frappe.db.get_value("Inspection",
			{"container": self.container, "inspection_type": "EIR-Out", "docstatus": 0}, "name")
		if hold_draft:
			self.track("Inspection", hold_draft)
			self.step("EIR-Out · open draft (compare to EIR-In + cert) (ESS)",
				lambda: ess_eir.eir_out_open(hold_draft))
			self.step("EIR-Out · submit DIRTY → Hold (ESS)",
				lambda: ess_eir.eir_save_draft(inspection=hold_draft, inspection_type="EIR-Out",
					referred_voucher=self.order_muat, exterior_condition="Dirty", seals_intact=0, submit=1))
			self.assert_true("EIR-Out · outcome Hold + Order Muat Hold",
				frappe.db.get_value("Inspection", hold_draft, "out_outcome") == "Hold Pending Clearance"
				and frappe.db.get_value("Order Muat", self.order_muat, "order_status") == "Hold")

		# --- 17) EIR-Out READY (clean) -----------------------------------
		ready = self.step("EIR-Out · open fresh draft for clean pass (ESS)",
			lambda: ess_eir.eir_open_draft(container=self.container, inspection_type="EIR-Out"))
		ready_name = ready.get("inspection") if isinstance(ready, dict) else None
		if ready_name:
			self.track("Inspection", ready_name)
			self.step("EIR-Out · submit CLEAN → Ready To Load (ESS)",
				lambda: ess_eir.eir_save_draft(inspection=ready_name, inspection_type="EIR-Out",
					referred_voucher=self.order_muat, exterior_condition="Clean", seals_intact=1, submit=1))
			self.assert_true("EIR-Out · outcome Ready To Load",
				frappe.db.get_value("Inspection", ready_name, "out_outcome") == "Ready To Load")

		# --- 18) Gate Out (final) ----------------------------------------
		res = self.step("Gate Out · complete (ESS)", lambda: ess_gate.gate_out(container=self.container))
		if isinstance(res, dict):
			self.track("Gate Entry", res.get("gate_entry"))
		st = frappe.db.get_value("Container", self.container, ["status", "inventory_stage"], as_dict=True) or frappe._dict()
		self.assert_true("Gate Out · container Gate_Out + stage Departed",
			st.status == "Gate_Out" and st.inventory_stage == "Departed",
			f"status={st.status} stage={st.inventory_stage}")

		# --- 19) Verify the unified activity feed ------------------------
		feed = frappe.get_all("Container Activity", filters={"container": self.container},
			fields=["activity_type"], order_by="activity_time asc")
		types = {f.activity_type for f in feed}
		for needed in ["Booking", "Gate In", "Inspection (EIR)", "Cleaning", "Gate Out"]:
			self.assert_true(f"Activity feed · contains '{needed}'", needed in types, f"have={sorted(types)}")


# ---------------------------------------------------------------------------
# Read-only site probe (helper for adapting the script)
# ---------------------------------------------------------------------------
def probe():
	def cnt(dt, filters=None):
		try:
			return frappe.db.count(dt, filters or {})
		except Exception as e:
			return f"ERR {e}"
	_log("=== PROD SMOKE PROBE ===")
	_log(f"site={frappe.local.site}  user={frappe.session.user}  company={frappe.defaults.get_global_default('company')}")
	for dt in ["Company", "Branch", "Depot", "Customer Group", "Territory",
			"Cargo", "Inspection Damage Code", "Inspection Repair Code", "Inspection Checklist Item",
			"Cleaning Checklist Item", "Depot Service Menu", "Warehouse", "Mode of Payment"]:
		_log(f"  {dt:<28} {cnt(dt)}")
	for it in ["Lift Off", "Lift On"]:
		_log(f"  Item '{it}': exists={frappe.db.exists('Item', it)}")
	_log(f"  active Depot: {frappe.db.get_value('Depot', {'is_active':1}, ['name','branch'])}")
	_log(f"  a Yard Zone:  {frappe.db.get_value('Yard Zone', {}, ['name','depot','category'])}")
	_log(f"  non-stock sales item: {frappe.db.get_value('Item', {'is_stock_item':0,'disabled':0,'is_sales_item':1}, 'name')}")
	m = frappe.get_all("Inspection Damage Code", filters={"is_active": 1}, fields=["name"], limit=5)
	_log(f"  damage codes sample: {[r.name for r in m]}")
	ck = frappe.get_all("Inspection Checklist Item", filters={"is_active": 1}, fields=["item_code"], limit=3)
	_log(f"  checklist sample: {[r.item_code for r in ck]}")
	sm = frappe.get_all("Depot Service Menu", fields=["name", "is_active"])
	_log(f"  service menus: {[(r.name, r.is_active) for r in sm]}")
	_log(f"  leftover PRODTEST containers: {cnt('Container', {'name': ['like', CPREFIX + '%']})}")
	_log("=== END PROBE ===")


# ---------------------------------------------------------------------------
# Teardown — remove everything this (or any) PRODTEST run created, by prefix.
# ---------------------------------------------------------------------------
def _teardown(prefix=CPREFIX, cust_prefix=CUST_PREFIX):
	removed = 0

	def names(dt, filters):
		try:
			return frappe.get_all(dt, filters=filters, pluck="name")
		except Exception:
			return []

	def purge(dt, rows):
		"""Raw-delete each doc + its child-table rows. Bypasses docstatus checks and the
		``on_trash`` guards (Container Booking / Order * refuse normal deletion), so it
		reliably removes submitted rows. Safe here because we delete the whole related set
		together — no dangling links are left behind. None of our docs post GL/stock (Cash
		SIs are settled without a Payment Entry; M&R uses non-stock items)."""
		nonlocal removed
		try:
			children = [df.options for df in frappe.get_meta(dt).get_table_fields()]
		except Exception:
			children = []
		for name in rows:
			try:
				for child_dt in children:
					frappe.db.delete(child_dt, {"parent": name, "parenttype": dt})
				frappe.db.delete(dt, {"name": name})
				removed += 1
			except Exception as e:
				_log(f"   (delete {dt} {name} skipped: {str(e).splitlines()[0][:80]})")

	# Scope by TAG PREFIX first (robust even when a parent customer/booking was already
	# deleted, e.g. an orphan left by an aborted run), then broaden via links.
	like = f"%{prefix}%"
	conts = names("Container", {"name": ["like", f"{prefix}%"]})
	custs = names("Customer", {"customer_name": ["like", f"{cust_prefix}%"]})
	bookings = list(set(
		(names("Container Booking", {"customer": ["in", custs or [""]]}) if custs else [])
		+ names("Container Booking", {"do_reference": ["like", like]})
	))
	codes = names("Booking Code", {"container_no": ["like", f"{prefix}%"]})
	if bookings:
		codes = list(set(codes + names("Booking Code", {"booking": ["in", bookings]})))
	orders_b = names("Order Bongkar", {"booking": ["in", bookings or [""]]}) if bookings else []
	orders_m = names("Order Muat", {"booking": ["in", bookings or [""]]}) if bookings else []
	gate = names("Gate Entry", {"container_no": ["like", f"{prefix}%"]})
	insp = names("Inspection", {"container": ["in", conts or [""]]}) if conts else []
	clean = names("Cleaning Order", {"container": ["in", conts or [""]]}) if conts else []
	ro = names("Repair Order", {"container": ["in", conts or [""]]}) if conts else []
	# Release DO: by tank_owner OR by its child containers (survives a deleted customer).
	rdo = list(set(
		(names("Release DO", {"tank_owner": ["in", custs or [""]]}) if custs else [])
		+ names("Release DO", {"tank_owner": ["like", f"{cust_prefix}%"]})
		+ frappe.get_all("Release DO Item", filters={"container": ["like", f"{prefix}%"]}, pluck="parent")
	))
	# Sales Invoice: by customer OR our tagged remarks.
	si = list(set(
		(names("Sales Invoice", {"customer": ["in", custs or [""]]}) if custs else [])
		+ names("Sales Invoice", {"remarks": ["like", like]})
	))
	# Payment Entry: referencing our SIs OR carrying our tag as the reference number.
	pe = list(set(
		[p for s in si for p in _payment_entries_for_invoice(s)]
		+ names("Payment Entry", {"reference_no": ["like", f"{prefix}%"]})
	))
	se = names("Stock Entry", {"name": ["in", [r.stock_entry for r in frappe.get_all(
		"Repair Order", filters={"name": ["in", ro or [""]]}, fields=["stock_entry"]) if getattr(r, "stock_entry", None)] or [""]]}) if ro else []
	act = names("Container Activity", {"container": ["in", conts or [""]]}) if conts else []
	mov = names("Container Movement", {"container": ["in", conts or [""]]}) if conts else []
	contracts = names("Depot Contract", {"customer": ["in", custs or [""]]}) if custs else []
	pricelists = names("Price List", {"customer": ["in", custs or [""]]}) if custs else []

	# Notifications that point at any of our docs.
	all_doc_names = set(conts + bookings + orders_b + orders_m + gate + insp + clean + cert + ro + rdo + si)
	notif = names("Notification Log", {"document_name": ["in", list(all_doc_names) or [""]]}) if all_doc_names else []

	_log(f"teardown scope: {len(conts)} containers, {len(bookings)} bookings, {len(orders_b)+len(orders_m)} orders, "
		f"{len(gate)} gate, {len(insp)} EIR, {len(clean)} cleaning, {len(cert)} cert, {len(ro)} M&R, "
		f"{len(rdo)} release, {len(si)} SI, {len(pe)} PE, {len(se)} SE, {len(custs)} customers")

	# Defensive: drop any ledger rows our vouchers posted. The current flow posts NONE
	# (Cash SIs are settled without a Payment Entry; M&R uses non-stock items), but this
	# also sweeps orphan GL rows left by earlier iterations whose voucher docs are gone —
	# match by our tag in the remarks as well as by our (still-known) voucher numbers.
	vouchers = list(set(si + pe + se))
	for ledger in ("GL Entry", "Payment Ledger Entry", "Stock Ledger Entry"):
		for filt in ([{"voucher_no": ["in", vouchers]}] if vouchers else []) + [{"remarks": ["like", like]}]:
			try:
				frappe.db.delete(ledger, filt)
			except Exception:
				pass  # ledger may lack a 'remarks' column (Stock/Payment Ledger) — ignore

	# Purge everything (transactionals first, then masters). Order is not critical —
	# raw deletes ignore inter-doc links — but transactionals-before-masters keeps it tidy.
	for dt, rows in [
		("Payment Entry", pe), ("Sales Invoice", si), ("Stock Entry", se),
		("Gate Entry", gate), ("Inspection", insp),
		("Cleaning Order", clean), ("Repair Order", ro), ("Release DO", rdo),
		("Order Muat", orders_m), ("Order Bongkar", orders_b),
		("Booking Code", codes), ("Container Booking", bookings),
		("Container Activity", act), ("Container Movement", mov),
		("Notification Log", notif), ("Container", conts),
		("Depot Contract", contracts),
	]:
		purge(dt, rows)

	for name in pricelists:
		frappe.db.delete("Item Price", {"price_list": name})
	purge("Price List", pricelists)
	purge("Customer", custs)

	frappe.db.commit()
	_log(f"Teardown: {removed} docs removed (tag prefix {prefix}).")
	return removed


def _payment_entries_for_invoice(sales_invoice):
	try:
		return frappe.get_all(
			"Payment Entry Reference",
			filters={"reference_doctype": "Sales Invoice", "reference_name": sales_invoice},
			pluck="parent",
		)
	except Exception:
		return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run(scenario="all", keep=0, cleanup_only=0, tag=None):
	frappe.set_user("Administrator")
	if int(cleanup_only or 0):
		_teardown()
		return {"cleanup_only": True}

	r = SmokeRun(tag=tag, keep=bool(int(keep or 0)))
	_log(f"\n########## PROD SMOKE START (tag {r.tag}) ##########")
	try:
		r.ensure_masters()
		if scenario in ("all", "in"):
			r.tank_in()
		if scenario in ("all", "out"):
			r.tank_out()
	finally:
		if r.keep:
			_log("keep=1 → skipping teardown (remember to run cleanup_only=1 later).")
			frappe.db.commit()
		else:
			_teardown()
	passed, failed = r.summary()
	return {"tag": r.tag, "passed": passed, "failed": failed}
