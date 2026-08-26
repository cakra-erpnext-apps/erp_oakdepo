"""Storage day accounting — the days engine and the Storage Charges report.

The point of these tests is the DAY COUNT, not the money: rates may legitimately be 0
here (no rate card is seeded), and every assertion is about how many nights the depot may
charge for.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from container_depot import storage, storage_charge
from container_depot.container_depot.report.storage_charges.storage_charges import execute
from container_depot.tests.test_api import ensure_test_customer

PREFIX = "STGCHG"


def _container(cno, status, principal, **kwargs):
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": cno,
		"container_type": "ISO Tank",
		"size": "20'",
		"status": status,
		"principal": principal,
		**kwargs,
	}).insert(ignore_permissions=True)


def _gate_entry(cno, gate_in, gate_out=None):
	"""A visit, exactly as the gate records one: a DRAFT Gate Entry carrying both
	timestamps (submitting one would drive the container's status, which these tests set
	themselves)."""
	return frappe.get_doc({
		"doctype": "Gate Entry",
		"container_no": cno,
		"gate_in_timestamp": f"{gate_in} 08:00:00",
		"gate_out_timestamp": f"{gate_out} 08:00:00" if gate_out else None,
		"status": "Gate_In_Completed" if not gate_out else "Gate_Out_Completed",
	}).insert(ignore_permissions=True)


class TestStorageCharges(FrappeTestCase):
	def setUp(self):
		self.customer = ensure_test_customer("Storage Charge Owner")
		self._prev_free = frappe.db.get_single_value("Depot Finance Settings", "storage_free_days")
		self._prev_mode = frappe.db.get_single_value("Depot Finance Settings", "storage_day_count")
		frappe.db.set_single_value("Depot Finance Settings", "storage_free_days", 0)
		frappe.db.set_single_value("Depot Finance Settings", "storage_day_count", storage.COUNT_BOTH)

	def tearDown(self):
		"""Restore the site to its pre-test state — the settings singleton included, or the
		next run inherits this run's free days."""
		frappe.db.set_single_value("Depot Finance Settings", "storage_free_days", self._prev_free)
		frappe.db.set_single_value("Depot Finance Settings", "storage_day_count", self._prev_mode)
		for cno in frappe.get_all("Container", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name"):
			frappe.db.delete("Storage Charge", {"container": cno})
			frappe.db.delete("Container Movement", {"container": cno})
			frappe.db.delete("Container Activity", {"container": cno})
			frappe.db.delete("Container", {"name": cno})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.commit()

	# --- the closed stay: the case that used to count zero ------------------- #
	def test_closed_stay_is_charged(self):
		"""A tank that gated out is still billable for the nights it stayed."""
		cno = f"{PREFIX}CLOSED"
		_container(cno, "Gate_Out", self.customer)
		_gate_entry(cno, add_days(today(), -10), add_days(today(), -8))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "mode": "Semua",
		})
		row = next(r for r in rows if r["container"] == cno)
		self.assertEqual(row["stay_days"], 3)          # in + middle + out day
		self.assertEqual(row["chargeable_days"], 3)
		self.assertEqual(row["stay_status"], "Sudah Keluar")
		self.assertEqual(row["source"], storage.SRC_GATE)

	def test_running_stay_accrues_to_cutoff(self):
		cno = f"{PREFIX}OPEN"
		_container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -4))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "mode": "Semua",
		})
		row = next(r for r in rows if r["container"] == cno)
		self.assertEqual(row["chargeable_days"], 5)     # day -4 .. today, inclusive
		self.assertIsNone(row["out_date"])
		self.assertEqual(row["stay_status"], "Masih Menginap")

	def test_cutoff_never_bills_the_future(self):
		"""A To Date in the future must not charge for nights that have not happened."""
		cno = f"{PREFIX}FUTURE"
		_container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -2))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": add_days(today(), 30),
			"principal": self.customer, "mode": "Semua",
		})
		row = next(r for r in rows if r["container"] == cno)
		self.assertEqual(row["chargeable_days"], 3)

	# --- free days ----------------------------------------------------------- #
	def test_free_days_come_off_the_start_of_the_stay(self):
		frappe.db.set_single_value("Depot Finance Settings", "storage_free_days", 3)
		cno = f"{PREFIX}FREE"
		_container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -5))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "mode": "Semua",
		})
		row = next(r for r in rows if r["container"] == cno)
		self.assertEqual(row["stay_days"], 6)           # the stay itself is unchanged
		self.assertEqual(row["chargeable_days"], 3)     # 6 nights - 3 free
		self.assertEqual(row["charge_from"], add_days(getdate(today()), -2))

	def test_free_days_can_swallow_a_short_stay(self):
		frappe.db.set_single_value("Depot Finance Settings", "storage_free_days", 7)
		cno = f"{PREFIX}SHORT"
		_container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -2))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "show_zero": 1, "mode": "Semua",
		})
		row = next(r for r in rows if r["container"] == cno)
		self.assertEqual(row["chargeable_days"], 0)

	# --- the anti-double-charge watermark ------------------------------------ #
	def test_billed_until_trims_what_was_already_charged(self):
		"""The running mode charged up to a point; the closing bill starts after it.

		The watermark is read from the visit's own Storage Charge row — see
		:class:`TestStorageChargeLedger` for why it cannot live on the container.
		"""
		cno = f"{PREFIX}WATER"
		doc = _container(cno, "Gate_Out", self.customer)
		_gate_entry(cno, add_days(today(), -10), add_days(today(), -3))
		storage_charge.sync(doc.name, cno)
		visit = frappe.db.get_value("Storage Charge", {"container": doc.name}, "name")
		frappe.db.set_value("Storage Charge", visit, "billed_until", add_days(today(), -6))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "mode": "Semua",
		})
		row = next(r for r in rows if r["container"] == cno)
		self.assertEqual(row["stay_days"], 8)           # the whole stay, for reference
		self.assertEqual(row["chargeable_days"], 3)     # day -5, -4, -3
		self.assertEqual(row["charge_from"], add_days(getdate(today()), -5))

	# --- re-entry ------------------------------------------------------------ #
	def test_two_visits_are_two_rows(self):
		cno = f"{PREFIX}TWICE"
		_container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -20), add_days(today(), -18))
		_gate_entry(cno, add_days(today(), -4))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "mode": "Semua",
		})
		mine = [r for r in rows if r["container"] == cno]
		self.assertEqual(len(mine), 2)
		self.assertEqual({r["chargeable_days"] for r in mine}, {3, 5})
		self.assertEqual(
			storage.days_in_depot(cno, add_days(today(), -30), today()), 8
		)

	# --- filters + conventions ----------------------------------------------- #
	def test_mode_filter_splits_the_two_ways_of_charging(self):
		open_no, closed_no = f"{PREFIX}MODEIN", f"{PREFIX}MODEOUT"
		_container(open_no, "In_Depot", self.customer)
		_gate_entry(open_no, add_days(today(), -3))
		_container(closed_no, "Gate_Out", self.customer)
		_gate_entry(closed_no, add_days(today(), -9), add_days(today(), -7))
		base = {"from_date": add_days(today(), -30), "to_date": today(), "principal": self.customer}

		_, running = execute({**base, "mode": "Masih Menginap"})
		self.assertEqual({r["container"] for r in running}, {open_no})
		_, closed = execute({**base, "mode": "Sudah Keluar"})
		self.assertEqual({r["container"] for r in closed}, {closed_no})
		_, both = execute({**base, "mode": "Semua"})
		self.assertEqual({r["container"] for r in both}, {open_no, closed_no})

	def test_out_day_can_be_excluded(self):
		frappe.db.set_single_value(
			"Depot Finance Settings", "storage_day_count", storage.COUNT_NO_OUT
		)
		cno = f"{PREFIX}NOOUT"
		_container(cno, "Gate_Out", self.customer)
		_gate_entry(cno, add_days(today(), -10), add_days(today(), -8))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "mode": "Semua",
		})
		row = next(r for r in rows if r["container"] == cno)
		self.assertEqual(row["chargeable_days"], 2)     # 3 under the other convention

	def test_window_excludes_a_stay_that_ended_before_it(self):
		cno = f"{PREFIX}OLD"
		_container(cno, "Gate_Out", self.customer)
		_gate_entry(cno, add_days(today(), -60), add_days(today(), -55))
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "show_zero": 1, "mode": "Semua",
		})
		self.assertFalse([r for r in rows if r["container"] == cno])

	def test_booked_tank_has_nothing_to_charge(self):
		cno = f"{PREFIX}BOOKED"
		_container(cno, "Booked", self.customer)
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "show_zero": 1, "mode": "Semua",
		})
		self.assertFalse([r for r in rows if r["container"] == cno])

	# --- fallback sources ----------------------------------------------------- #
	def test_falls_back_to_the_status_trail_without_a_gate_entry(self):
		"""No Gate Entry: the movement log answers, and says so in Sumber."""
		cno = f"{PREFIX}NOGATE"
		doc = _container(cno, "In_Depot", self.customer)
		periods = storage.stay_periods(doc.name, cno)
		self.assertTrue(periods)
		self.assertEqual(periods[0]["source"], storage.SRC_MOVEMENT)
		self.assertIsNone(periods[0]["end"])

	def test_report_columns_shape(self):
		columns, _ = execute({})
		names = {c["fieldname"] for c in columns}
		self.assertTrue(
			{"container", "in_date", "out_date", "stay_days", "free_days", "chargeable_days", "source"}
			<= names
		)


class TestStorageBillingMode(FrappeTestCase):
	"""The per-owner policy: WHICH stays a tank owner may be charged for at all."""

	def setUp(self):
		self.customer = ensure_test_customer("Storage Mode Owner")
		self._prev_mode = frappe.db.get_single_value("Depot Finance Settings", "storage_billing_mode")
		self._prev_free = frappe.db.get_single_value("Depot Finance Settings", "storage_free_days")
		frappe.db.set_single_value("Depot Finance Settings", "storage_free_days", 0)
		frappe.db.set_single_value("Depot Finance Settings", "storage_billing_mode", storage.MODE_RUNNING)
		self.contract = None

	def tearDown(self):
		frappe.db.set_single_value("Depot Finance Settings", "storage_billing_mode", self._prev_mode)
		frappe.db.set_single_value("Depot Finance Settings", "storage_free_days", self._prev_free)
		if self.contract:
			# Only a Draft contract may be deleted (Void/Amend is the real-world path for the
			# rest), and activating one publishes a customer Price List — both have to go, or
			# the next run inherits a contract that silently answers billing_mode_for.
			price_list = frappe.db.get_value("Depot Contract", self.contract, "generated_price_list")
			frappe.db.set_value("Depot Contract", self.contract, "status", "Draft")
			frappe.delete_doc("Depot Contract", self.contract, force=True, ignore_permissions=True)
			if price_list and frappe.db.exists("Price List", price_list):
				frappe.db.delete("Item Price", {"price_list": price_list})
				frappe.delete_doc("Price List", price_list, force=True, ignore_permissions=True)
		for cno in frappe.get_all("Container", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name"):
			frappe.db.delete("Storage Charge", {"container": cno})
			frappe.db.delete("Container Movement", {"container": cno})
			frappe.db.delete("Container Activity", {"container": cno})
			frappe.db.delete("Container", {"name": cno})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.commit()

	def _contract(self, mode):
		doc = frappe.get_doc({
			"doctype": "Depot Contract",
			"customer": self.customer,
			"status": "Active",
			"payment_type": "Cash",
			"currency": "IDR",
			"valid_from": add_days(today(), -365),
			"valid_to": add_days(today(), 365),
			"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
			"storage_billing_mode": mode,
		}).insert(ignore_permissions=True)
		self.contract = doc.name
		return doc

	def _yard(self):
		"""One tank still inside, one that has already left."""
		open_no, closed_no = f"{PREFIX}MODEOPEN", f"{PREFIX}MODEDONE"
		_container(open_no, "In_Depot", self.customer)
		_gate_entry(open_no, add_days(today(), -5))
		_container(closed_no, "Gate_Out", self.customer)
		_gate_entry(closed_no, add_days(today(), -12), add_days(today(), -10))
		return open_no, closed_no

	def _rows(self, **extra):
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, **extra,
		})
		return {r["container"] for r in rows}

	def test_on_exit_owner_hides_tanks_still_inside(self):
		"""Cara pertama: nothing is chargeable until the tank has gated out."""
		self._contract(storage.MODE_ON_EXIT)
		open_no, closed_no = self._yard()
		self.assertEqual(self._rows(), {closed_no})

	def test_running_owner_gets_both(self):
		"""Cara kedua: the open stay accrues, and the closed one still owes its tail."""
		self._contract(storage.MODE_RUNNING)
		open_no, closed_no = self._yard()
		self.assertEqual(self._rows(), {open_no, closed_no})

	def test_empty_contract_mode_follows_the_global_default(self):
		self._contract("")
		frappe.db.set_single_value("Depot Finance Settings", "storage_billing_mode", storage.MODE_ON_EXIT)
		open_no, closed_no = self._yard()
		self.assertEqual(self._rows(), {closed_no})
		self.assertEqual(storage.billing_mode_for(self.customer), storage.MODE_ON_EXIT)

	def test_default_is_charge_on_exit(self):
		"""No contract, no global setting: a tank owner is billed when the tank leaves."""
		frappe.db.set_single_value("Depot Finance Settings", "storage_billing_mode", None)
		self.assertEqual(storage.billing_mode_for(self.customer), storage.MODE_ON_EXIT)
		open_no, closed_no = self._yard()
		self.assertEqual(self._rows(), {closed_no})

	def test_contract_beats_the_global_default(self):
		self._contract(storage.MODE_RUNNING)
		frappe.db.set_single_value("Depot Finance Settings", "storage_billing_mode", storage.MODE_ON_EXIT)
		self.assertEqual(storage.billing_mode_for(self.customer), storage.MODE_RUNNING)

	def test_stay_filter_overrides_the_contract(self):
		"""The stay-status filters inspect the yard, so they ignore the policy."""
		self._contract(storage.MODE_ON_EXIT)
		open_no, closed_no = self._yard()
		self.assertEqual(self._rows(mode="Masih Menginap"), {open_no})
		self.assertEqual(self._rows(mode="Semua"), {open_no, closed_no})

	def test_mode_is_shown_on_every_row(self):
		self._contract(storage.MODE_ON_EXIT)
		self._yard()
		_, rows = execute({
			"from_date": add_days(today(), -30), "to_date": today(),
			"principal": self.customer, "mode": "Semua",
		})
		self.assertEqual({r["billing_mode"] for r in rows}, {storage.MODE_ON_EXIT})


class TestStorageChargeLedger(FrappeTestCase):
	"""One record per visit — the thing a single per-container watermark could not do."""

	def setUp(self):
		self.customer = ensure_test_customer("Storage Ledger Owner")
		self._prev_free = frappe.db.get_single_value("Depot Finance Settings", "storage_free_days")
		self._prev_mode = frappe.db.get_single_value("Depot Finance Settings", "storage_billing_mode")
		frappe.db.set_single_value("Depot Finance Settings", "storage_free_days", 0)
		frappe.db.set_single_value("Depot Finance Settings", "storage_billing_mode", storage.MODE_ON_EXIT)

	def tearDown(self):
		frappe.db.set_single_value("Depot Finance Settings", "storage_free_days", self._prev_free)
		frappe.db.set_single_value("Depot Finance Settings", "storage_billing_mode", self._prev_mode)
		for cno in frappe.get_all("Container", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name"):
			frappe.db.delete("Storage Charge", {"container": cno})
			frappe.db.delete("Container Movement", {"container": cno})
			frappe.db.delete("Container Activity", {"container": cno})
			frappe.db.delete("Container", {"name": cno})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.commit()

	def _visits(self, container):
		return frappe.get_all(
			"Storage Charge", filters={"container": container},
			fields=["name", "date_in", "date_out", "status", "stay_days", "billed_days", "unbilled_days", "billed_until"],
			order_by="date_in asc",
		)

	def test_a_visit_is_recorded_when_the_tank_arrives(self):
		cno = f"{PREFIX}LEDGIN"
		doc = _container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -3))
		storage_charge.sync(doc.name, cno)
		visits = self._visits(doc.name)
		self.assertEqual(len(visits), 1)
		self.assertEqual(visits[0].status, storage_charge.RUNNING)
		self.assertIsNone(visits[0].date_out)
		self.assertEqual(visits[0].stay_days, 4)

	def test_leaving_closes_the_visit_as_unpaid(self):
		cno = f"{PREFIX}LEDGOUT"
		doc = _container(cno, "Gate_Out", self.customer)
		_gate_entry(cno, add_days(today(), -6), add_days(today(), -4))
		storage_charge.sync(doc.name, cno)
		visit = self._visits(doc.name)[0]
		self.assertEqual(visit.status, storage_charge.UNPAID)
		self.assertEqual(visit.unbilled_days, 3)
		self.assertEqual(visit.billed_days, 0)

	def test_each_visit_keeps_its_own_billed_state(self):
		"""The whole point: billing visit 2 must not mark visit 1 as billed."""
		cno = f"{PREFIX}LEDGTWO"
		doc = _container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -40), add_days(today(), -35))   # visit 1, unbilled
		_gate_entry(cno, add_days(today(), -10))                            # visit 2, running
		storage_charge.sync(doc.name, cno)
		first, second = self._visits(doc.name)

		# Visit 2 gets billed right up to today.
		frappe.db.set_value("Storage Charge", second.name, "billed_until", today())
		storage_charge.sync(doc.name, cno)
		first, second = self._visits(doc.name)

		self.assertEqual(first.unbilled_days, 6)      # July's days survive
		self.assertEqual(first.status, storage_charge.UNPAID)
		self.assertEqual(second.unbilled_days, 0)
		self.assertEqual(second.billed_days, 11)

	def test_the_report_shows_an_older_unpaid_visit_even_though_it_is_not_the_newest(self):
		cno = f"{PREFIX}LEDGSHOW"
		doc = _container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -40), add_days(today(), -35))
		_gate_entry(cno, add_days(today(), -10))
		storage_charge.sync(doc.name, cno)
		_, rows = execute({
			"from_date": add_days(today(), -60), "to_date": today(),
			"principal": self.customer, "mode": "Semua",
		})
		self.assertEqual(len(rows), 2)

	def test_a_settled_older_visit_is_hidden_unless_all_visits_is_ticked(self):
		cno = f"{PREFIX}LEDGHIDE"
		doc = _container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -40), add_days(today(), -35))
		_gate_entry(cno, add_days(today(), -10))
		storage_charge.sync(doc.name, cno)
		old_visit = self._visits(doc.name)[0]
		frappe.db.set_value("Storage Charge", old_visit.name, "billed_until", add_days(today(), -35))
		storage_charge.sync(doc.name, cno)

		base = {"from_date": add_days(today(), -60), "to_date": today(),
		        "principal": self.customer, "mode": "Semua", "show_zero": 1}
		_, rows = execute(base)
		self.assertEqual([r["container"] for r in rows], [cno])          # newest only
		_, all_rows = execute({**base, "all_visits": 1})
		self.assertEqual(len(all_rows), 2)
		self.assertEqual(
			frappe.db.get_value("Storage Charge", old_visit.name, "status"), storage_charge.PAID
		)

	def test_sync_is_idempotent(self):
		cno = f"{PREFIX}LEDGIDEM"
		doc = _container(cno, "In_Depot", self.customer)
		_gate_entry(cno, add_days(today(), -3))
		for _ in range(3):
			storage_charge.sync(doc.name, cno)
		self.assertEqual(len(self._visits(doc.name)), 1)
