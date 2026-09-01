"""Empat register yang menggantikan sheet Tank Inventory at KIM — Steam Wash, PP Wash,
Methanol Rinse, Periodic Test.

Yang dikunci di sini adalah dua hal yang membuat register ini berbeda dari daftar order
biasa, dan yang paling gampang hilang saat seseorang "merapikan" querynya nanti:

1. **Order yang belum selesai tetap tampil**, dengan kolom tanggal kosong. Itu backlognya
   — di sheet Steam Wash, 512 dari 537 baris memang tidak punya tanggal selesai. Register
   yang hanya memuat pekerjaan selesai menghapus pertanyaan yang dibawa orang ke sana.
2. **Order dikenali lewat jenis di header ATAU item code servicenya.** Sejak jenis
   ber-default Standard Cleaning, order steam yang headernya belum disetel Admin Ops hanya
   bisa dikenali dari item servicenya — dan tidak pernah dari NAMA item ("Steam Cleaning /
   Wash"), yang persis bug lama di report KPI.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, getdate, now_datetime

from container_depot.container_depot import register_history
from container_depot.container_depot.report.periodic_test_register import (
	periodic_test_register as pt_report,
)
from container_depot.container_depot.report.steam_wash_register import (
	steam_wash_register as steam_report,
)
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_cleaning_type import ensure_item

_PREFIX = "REGT"
_PRINCIPAL = "Register Test Principal"


class _RegisterCase(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.principal = ensure_test_customer(_PRINCIPAL)
		self._containers = []

	def tearDown(self):
		for c in self._containers:
			for dt in ("Cleaning Order", "Repair Order"):
				names = frappe.get_all(dt, filters={"container": c}, pluck="name")
				if names:
					child = "Cleaning Order Service" if dt == "Cleaning Order" else "Repair Used Item"
					frappe.db.delete(child, {"parent": ["in", names]})
				frappe.db.delete(dt, {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	def _container(self, suffix, **kw):
		name = frappe.get_doc({
			"doctype": "Container", "container_no": f"{_PREFIX}{suffix}",
			"container_type": "ISO Tank", "status": "In_Depot", "principal": self.principal,
			**kw,
		}).insert(ignore_permissions=True).name
		self._containers.append(name)
		return name

	def _mine(self, rows):
		"""Site dev / CI ikut memuat order lain; batasi ke tank milik test ini."""
		return [r for r in rows if (r["tank_no"] or "").startswith(_PREFIX)]


class TestWashRegister(_RegisterCase):
	def _cleaning(self, container, *, services=(), cleaning_type=None, completed=None):
		doc = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
			"cleaning_services": [{"cleaning_item": i} for i in services],
		})
		if cleaning_type:
			doc.cleaning_type = cleaning_type
		co = doc.insert(ignore_permissions=True)
		if completed:
			frappe.db.set_value("Cleaning Order", co.name, {
				"status": "Completed", "cleaning_end": completed, "docstatus": 1,
			}, update_modified=False)
		return co.name

	def test_order_is_listed_by_its_header_type(self):
		ensure_item("CLN-STANDARD", "Standard Clean")
		c = self._container("W1")
		self._cleaning(c, services=["CLN-STANDARD"], cleaning_type="Steam Wash")
		_cols, rows, _msg, _chart, _summary = steam_report.execute({})
		self.assertEqual([r["tank_no"] for r in self._mine(rows)], [c])

	def test_order_is_listed_by_its_service_item_code(self):
		"""Header masih Standard Cleaning (nilai default), tapi servicenya jelas steam."""
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		c = self._container("W2")
		self._cleaning(c, services=["INT-STEAM"])
		_cols, rows, _msg, _chart, _summary = steam_report.execute({})
		listed = self._mine(rows)
		self.assertEqual([r["tank_no"] for r in listed], [c])
		self.assertEqual(listed[0]["status"], "Service Setup")

	def test_plain_cleaning_order_is_not_listed(self):
		ensure_item("CLN-STANDARD", "Standard Clean")
		self._cleaning(self._container("W3"), services=["CLN-STANDARD"])
		_cols, rows, _msg, _chart, _summary = steam_report.execute({})
		self.assertEqual(self._mine(rows), [])

	def test_unfinished_order_is_listed_with_an_empty_date(self):
		"""Kolom tanggal yang kosong ITU backlognya — barisnya tidak boleh hilang."""
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		c = self._container("W4")
		self._cleaning(c, services=["INT-STEAM"])
		_cols, rows, _msg, _chart, _summary = steam_report.execute({})
		row = self._mine(rows)[0]
		self.assertIsNone(row["wash_date"])
		self.assertEqual(row["tank_no"], c)

	def test_completed_order_carries_its_wash_date(self):
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		c = self._container("W5")
		self._cleaning(c, services=["INT-STEAM"], completed=now_datetime())
		_cols, rows, _msg, _chart, _summary = steam_report.execute({})
		row = self._mine(rows)[0]
		self.assertEqual(getdate(row["wash_date"]), getdate())
		self.assertEqual(row["status"], "Completed")

	def test_only_outstanding_filter_drops_the_finished_ones(self):
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		open_tank = self._container("W6")
		done_tank = self._container("W7")
		self._cleaning(open_tank, services=["INT-STEAM"])
		self._cleaning(done_tank, services=["INT-STEAM"], completed=now_datetime())

		_cols, rows, _msg, _chart, summary = steam_report.execute({})
		self.assertEqual({r["tank_no"] for r in self._mine(rows)}, {open_tank, done_tank})

		_cols, rows, _msg, _chart, _summary = steam_report.execute({"only_outstanding": 1})
		self.assertEqual([r["tank_no"] for r in self._mine(rows)], [open_tank])
		# Ringkasan dihitung atas baris yang tampil, jadi angkanya selalu sejalan dengan tabel.
		self.assertEqual({s["label"] for s in summary}, {"Total Order", "Selesai", "Belum Selesai"})


class TestPeriodicTestRegister(_RegisterCase):
	def _repair(self, container, *, items=(), job_type="Periodic Test", completed=None, pt_type=None):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "job_type": job_type,
			"status": "Draft", "billing_status": "Unbilled", "pt_type": pt_type,
			"used_items": [{"line_type": "Jasa", "item": i, "quantity": 1} for i in items],
		}).insert(ignore_permissions=True)
		if completed:
			frappe.db.set_value("Repair Order", ro.name, {
				"status": "Completed", "completion_date": completed,
			}, update_modified=False)
		return ro.name

	def _rows(self, filters=None):
		_cols, rows, _msg, _chart, summary = pt_report.execute(filters or {})
		return self._mine(rows), summary

	def test_type_and_code_come_from_the_item_used(self):
		ensure_item("TEST-5-0YR", "5.0 Years Periodic Test")
		c = self._container("P1")
		self._repair(c, items=["TEST-5-0YR"])
		rows, _summary = self._rows()
		self.assertEqual(rows[0]["type_pt"], "5Y")
		self.assertEqual(rows[0]["code"], f"{self.principal}5Y")

	def test_header_type_wins_over_the_items(self):
		"""Kalau Admin Ops sudah menyatakan tipenya di header, tabel item tidak membantahnya
		— satu order bisa memuat uji fisik dan sertifikat kelasnya sekaligus."""
		ensure_item("TEST-2-5YR", "2.5 Years Periodic Test")
		c = self._container("P7")
		self._repair(c, items=["TEST-2-5YR"], pt_type="5Y")
		rows, _summary = self._rows()
		self.assertEqual(rows[0]["type_pt"], "5Y")
		self.assertEqual(rows[0]["code"], f"{self.principal}5Y")

	def test_repair_job_is_not_listed(self):
		ensure_item("TEST-5-0YR", "5.0 Years Periodic Test")
		self._repair(self._container("P2"), items=["TEST-5-0YR"], job_type="Repair")
		rows, _summary = self._rows()
		self.assertEqual(rows, [])

	def test_completed_order_gets_periodic_date_and_due_date(self):
		ensure_item("TEST-2-5YR", "2.5 Years Periodic Test")
		c = self._container("P3")
		self._repair(c, items=["TEST-2-5YR"], completed=now_datetime())
		rows, _summary = self._rows()
		row = rows[0]
		self.assertEqual(getdate(row["periodic_date"]), getdate())
		# 2,5Y = 30 bulan. next_pt_due dihapus v0_66, jadi jatuh tempo dihitung, bukan dibaca.
		self.assertEqual(getdate(row["due_date"]), getdate(add_months(getdate(), 30)))

	def test_plate_test_date_stands_in_when_the_tank_was_never_tested_here(self):
		ensure_item("TEST-5-0YR", "5.0 Years Periodic Test")
		plate = add_months(getdate(), -12)
		c = self._container("P4", last_test_date=plate)
		self._repair(c, items=["TEST-5-0YR"])
		rows, _summary = self._rows()
		self.assertEqual(getdate(rows[0]["last_pt_date"]), getdate(plate))
		# Data lama itu tidak menyimpan tipenya — kolomnya dikosongkan, bukan ditebak.
		self.assertEqual(rows[0]["last_pt_type"], "")

	def test_previous_test_in_the_system_wins_over_the_plate_date(self):
		ensure_item("TEST-2-5YR", "2.5 Years Periodic Test")
		ensure_item("TEST-5-0YR", "5.0 Years Periodic Test")
		c = self._container("P5", last_test_date=add_months(getdate(), -60))
		first = self._repair(c, items=["TEST-2-5YR"], completed=add_months(now_datetime(), -30))
		frappe.db.set_value(
			"Repair Order", first, "order_created", add_months(now_datetime(), -31),
			update_modified=False,
		)
		self._repair(c, items=["TEST-5-0YR"])

		rows, _summary = self._rows()
		latest = [r for r in rows if r["type_pt"] == "5Y"][0]
		self.assertEqual(latest["last_pt_type"], "2,5Y")
		self.assertEqual(getdate(latest["last_pt_date"]), getdate(add_months(getdate(), -30)))

	def test_summary_counts_the_overdue_ones(self):
		ensure_item("TEST-2-5YR", "2.5 Years Periodic Test")
		# Uji sebelumnya 40 bulan lalu -> jatuh tempo 10 bulan lalu, dan ujinya belum jalan.
		c = self._container("P6", last_test_date=add_months(getdate(), -40))
		self._repair(c, items=["TEST-2-5YR"])
		rows, summary = self._rows()
		self.assertTrue(getdate(rows[0]["due_date"]) < getdate())
		overdue = next(s for s in summary if s["label"] == "Lewat Due Date")
		self.assertGreaterEqual(overdue["value"], 1)
		self.assertEqual(overdue["indicator"], "Red")


class TestPlanAndActualDates(_RegisterCase):
	"""Tanggal rencana vs tanggal realisasi, dan siapa yang boleh menggesernya.

	Order sekarang bisa dibuat lebih dulu sebagai rencana (``plan_date``), dan tanggal
	realisasinya bisa diisi tangan — untuk pekerjaan yang dikerjakan kemarin tapi baru
	diinput hari ini, atau baris register lama yang dipindahkan dari sheet. Dua hal yang
	dikunci di sini: stempel otomatis tidak boleh menimpa tanggal yang sudah diisi, dan
	tanggal yang menentukan periode tagihan tidak boleh digeser setelah order ditagih.
	"""

	def test_supplied_order_date_survives_insert(self):
		"""Tanpa ini, stempel di before_insert menimpa tanggal aslinya diam-diam."""
		backdated = add_months(now_datetime(), -6)
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": self._container("D1"),
			"status": "Service Setup", "order_created": backdated,
		}).insert(ignore_permissions=True)
		self.assertEqual(getdate(co.order_created), getdate(backdated))

	def test_plan_date_is_kept_apart_from_the_actual_date(self):
		c = self._container("D2")
		plan = add_months(getdate(), 1)
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": c, "status": "Service Setup",
			"plan_date": plan,
		}).insert(ignore_permissions=True)
		self.assertEqual(getdate(co.plan_date), getdate(plan))
		# Rencana bukan realisasi: register dan penagihan membaca cleaning_end, yang masih
		# kosong sampai pekerjaannya benar-benar selesai.
		self.assertIsNone(co.cleaning_end)

	def test_billing_dates_are_locked_once_the_order_is_invoiced(self):
		c = self._container("D3")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": c, "status": "Service Setup",
		}).insert(ignore_permissions=True)
		frappe.db.set_value("Cleaning Order", co.name, "sales_invoice", "SINV-TEST-REGT",
				    update_modified=False)
		co.reload()
		co.cleaning_end = now_datetime()
		# Nomor invoicenya sengaja tidak ada: yang diuji penjaga tanggalnya, bukan link-nya.
		co.flags.ignore_links = True
		with self.assertRaises(frappe.ValidationError):
			co.save(ignore_permissions=True)

	def test_plan_date_stays_editable_after_invoicing(self):
		"""plan_date tidak dibaca penagihan, jadi ia tidak ikut dikunci."""
		c = self._container("D4")
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": c, "status": "Service Setup",
		}).insert(ignore_permissions=True)
		frappe.db.set_value("Cleaning Order", co.name, "sales_invoice", "SINV-TEST-REGT",
				    update_modified=False)
		co.reload()
		co.plan_date = getdate()
		co.flags.ignore_links = True
		co.save(ignore_permissions=True)
		self.assertEqual(getdate(co.plan_date), getdate())

	def test_repair_billing_dates_are_locked_once_billed(self):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": self._container("D5"),
			"job_type": "Repair", "status": "Draft", "billing_status": "Unbilled",
		}).insert(ignore_permissions=True)
		frappe.db.set_value("Repair Order", ro.name, "billing_status", "Principal Billed",
				    update_modified=False)
		ro.reload()
		ro.completion_date = now_datetime()
		with self.assertRaises(frappe.ValidationError):
			ro.save(ignore_permissions=True)


class TestTankHistory(_RegisterCase):
	"""Dialog riwayat di balik tiap baris register.

	Isinya diambil dari report registernya sendiri dengan filter container, jadi yang
	dikunci di sini terutama SATU hal: aturan "order mana milik jenis ini" tidak boleh
	punya salinan kedua — riwayat harus memuat order yang sama dengan yang tampil di
	tabel, termasuk yang dikenali lewat item code, dan tidak memuat tank lain.
	"""

	def _cleaning(self, container, item, *, completed=None, invoice=None):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
			"cleaning_services": [{"cleaning_item": item}],
		}).insert(ignore_permissions=True)
		values = {}
		if completed:
			values.update({"status": "Completed", "cleaning_end": completed, "docstatus": 1})
		if invoice:
			values["sales_invoice"] = invoice
		if values:
			frappe.db.set_value("Cleaning Order", co.name, values, update_modified=False)
		return co.name

	def test_history_lists_every_wash_of_that_tank_newest_first(self):
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		c = self._container("H1")
		old = self._cleaning(c, "INT-STEAM", completed=add_months(now_datetime(), -2))
		frappe.db.set_value("Cleaning Order", old, "order_created", add_months(now_datetime(), -2),
				    update_modified=False)
		new = self._cleaning(c, "INT-STEAM")

		got = register_history.tank_history(c, "Steam Wash")
		self.assertEqual([r["cleaning_order"] for r in got["rows"]], [new, old])

	def test_history_carries_the_invoice_when_there_is_one(self):
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		c = self._container("H2")
		self._cleaning(c, "INT-STEAM", completed=now_datetime(), invoice="SINV-HIST-REGT")
		got = register_history.tank_history(c, "Steam Wash")
		self.assertEqual(got["rows"][0]["sales_invoice"], "SINV-HIST-REGT")
		self.assertIn("sales_invoice", {c2["fieldname"] for c2 in got["columns"]})

	def test_history_is_scoped_to_the_tank_that_was_clicked(self):
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		mine = self._container("H3")
		other = self._container("H4")
		self._cleaning(mine, "INT-STEAM")
		self._cleaning(other, "INT-STEAM")
		got = register_history.tank_history(mine, "Steam Wash")
		self.assertEqual(len(got["rows"]), 1)

	def test_periodic_test_history_carries_type_and_invoice(self):
		ensure_item("TEST-5-0YR", "5.0 Years Periodic Test")
		c = self._container("H5")
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": c, "job_type": "Periodic Test",
			"pt_type": "5Y", "status": "Draft", "billing_status": "Unbilled",
			"used_items": [{"line_type": "Jasa", "item": "TEST-5-0YR", "quantity": 1}],
		}).insert(ignore_permissions=True)
		frappe.db.set_value("Repair Order", ro.name, "sales_invoice", "SINV-HIST-REGT",
				    update_modified=False)
		got = register_history.tank_history(c, "Periodic Test")
		self.assertEqual(got["rows"][0]["type_pt"], "5Y")
		self.assertEqual(got["rows"][0]["sales_invoice"], "SINV-HIST-REGT")

	def test_tank_no_and_principal_are_dropped_from_the_dialog(self):
		"""Nomor tank sudah jadi judul dialognya, dan principal tidak berubah antar baris."""
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		c = self._container("H6")
		self._cleaning(c, "INT-STEAM")
		fields = {c2["fieldname"] for c2 in register_history.tank_history(c, "Steam Wash")["columns"]}
		self.assertNotIn("tank_no", fields)
		self.assertNotIn("principal", fields)

	def test_unknown_register_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			register_history.tank_history(self._container("H7"), "Bukan Register")
