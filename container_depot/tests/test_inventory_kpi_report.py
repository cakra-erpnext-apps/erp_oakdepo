"""Inventory KPI per Principal — the per-principal roll-up behind the depot dashboard.

The report once crashed in production with ``Table 'tabPeriodic Test' doesn't exist``: it
still queried a doctype that had been dropped out from under it, and nothing executed the
report in CI. The smoke test below is the guard — it runs every query the report issues, so
any other doctype that gets renamed or dropped fails here instead of in the browser.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.report.inventory_kpi_per_principal.inventory_kpi_per_principal import (
	execute,
)
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_cleaning_type import ensure_item

_DEPOT = "OAK1"
_PRINCIPAL = "KPI Wash Test Principal"
_PREFIX = "KPIWASH"


class TestInventoryKpiReport(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_runs_without_error_and_has_expected_columns(self):
		columns, data = execute({})
		names = {c["fieldname"] for c in columns}
		self.assertTrue({"principal", "stock_in_depo", "total_cleaned"} <= names)
		self.assertIsInstance(data, list)

	def test_depot_filter_runs_every_query(self):
		"""The depot-scoped branch takes a different code path in each sub-query."""
		columns, data = execute({"depot": _DEPOT})
		self.assertTrue(columns)
		self.assertIsInstance(data, list)


class TestInventoryKpiWashColumns(FrappeTestCase):
	"""Kolom PP Wash / Methanol / Steam benar-benar menghitung.

	Selama berbulan-bulan ketiganya konstan nol: matching-nya ``cos.item_name LIKE
	'%Steam Wash%'`` sementara item-nya bernama "Steam Cleaning / Wash" — dan cabang
	``cleaning_type`` di sebelahnya juga kosong karena field itu masih hidden. Nol yang
	sempurna terbaca sebagai "belum ada wash khusus", bukan sebagai laporan yang rusak,
	jadi tidak ada yang melaporkannya. Test ini yang mengunci: satu order Steam dan satu
	order Standard untuk principal yang sama harus terbaca 1, bukan 0 dan bukan 2.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.principal = ensure_test_customer(_PRINCIPAL)
		self._containers = []

	def tearDown(self):
		for c in self._containers:
			orders = frappe.get_all("Cleaning Order", filters={"container": c}, pluck="name")
			if orders:
				frappe.db.delete("Cleaning Order Service", {"parent": ["in", orders]})
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	def _completed_order(self, cno, item, cleaning_type=None):
		container = frappe.get_doc({
			"doctype": "Container", "container_no": cno, "container_type": "ISO Tank",
			"status": "In_Depot", "principal": self.principal,
		}).insert(ignore_permissions=True).name
		self._containers.append(container)
		doc = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
			"cleaning_services": [{"cleaning_item": item}],
		})
		if cleaning_type:
			doc.cleaning_type = cleaning_type
		co = doc.insert(ignore_permissions=True)
		# Report membaca DB langsung; docstatus/status disetel di sini supaya test tidak
		# ikut menempuh seluruh alur lapangan hanya untuk menghasilkan satu baris selesai.
		frappe.db.set_value(
			"Cleaning Order", co.name, {"docstatus": 1, "status": "Completed"}, update_modified=False
		)
		return co.name

	def test_steam_column_counts_the_steam_order_only(self):
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		ensure_item("CLN-STANDARD", "Standard Clean")
		self._completed_order(f"{_PREFIX}001", "INT-STEAM")
		self._completed_order(f"{_PREFIX}002", "CLN-STANDARD")

		_, data = execute({})
		row = next(r for r in data if r["principal"] == self.principal)
		self.assertEqual(row["steam"], 1)
		self.assertEqual(row["total_cleaned"], 2)
		self.assertEqual(row["pp_wash"], 0)
		self.assertEqual(row["methanol"], 0)

	def test_wash_service_is_counted_even_when_the_header_says_other(self):
		"""Jalur kedua: item CODE service, untuk order yang header-nya bukan jenis itu.

		Ini yang mengunci perpindahan dari ``cos.item_name LIKE '%Steam Wash%'`` ke
		``cos.cleaning_item = 'INT-STEAM'``. Nama item ("Steam Cleaning / Wash") milik
		finance dan boleh berubah; item code tidak.
		"""
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		self._completed_order(f"{_PREFIX}003", "INT-STEAM", cleaning_type="Other")

		_, data = execute({})
		row = next(r for r in data if r["principal"] == self.principal)
		self.assertEqual(row["steam"], 1)
