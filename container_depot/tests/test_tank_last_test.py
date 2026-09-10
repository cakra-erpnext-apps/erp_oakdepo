"""Tgl. Tes Terakhir tank (``Container.last_test_date``): siapa yang menulisnya.

Dua penulis, satu field, dan itu memang inti rancangannya — layar mana pun yang menampilkan
"Tgl. Tes Terakhir" membaca satu nilai yang sama, jadi tanggal yang dibetulkan sambil membuka
order cuci adalah tanggal yang dicetak EIR berikutnya:

* **Uji di depo sendiri** — M&R ber-``job_type = Periodic Test`` yang ditutup menstempelnya
  sendiri (``RepairOrder._stamp_last_test_date``). Inilah "default dari tes kita".
* **Uji di luar** — vendor atau depo lain, yang tidak akan pernah punya dokumennya di sini,
  diketik lewat ``container.set_last_test_date`` dari form order (PWA maupun Desk).

Yang dijaga di sini adalah tabrakan antara keduanya: stempel otomatis tidak boleh menimpa
tanggal yang lebih baru yang sudah diketik orang, dan tanggal yang diketik orang harus lolos
dua saringan salah-ketik (masa depan, dan sebelum tank-nya dibuat).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from container_depot.container_depot.doctype.container.container import set_last_test_date
from container_depot.tests.test_eir import _make_container


class TestTankLastTestDate(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._orders = []

	def tearDown(self):
		for name in self._orders:
			frappe.db.delete("Repair Order", {"name": name})
		for c in self._containers:
			frappe.db.delete("Repair Order", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Comment", {"reference_doctype": "Container", "reference_name": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	# --- fixtures ------------------------------------------------------------
	def _container(self, cno, **kw):
		name = _make_container(cno, **kw)
		self._containers.append(name)
		return name

	def _periodic_test(self, container, *, completion_date, status="Completed"):
		"""M&R uji berkala yang langsung lahir dalam status akhirnya.

		Sah: ``_validate_status_transition`` hanya menilai PERPINDAHAN status, dan dokumen
		baru tidak punya status sebelumnya — sama seperti order yang dibuat otomatis dari EIR.
		"""
		doc = frappe.get_doc({
			"doctype": "Repair Order",
			"container": container,
			"job_type": "Periodic Test",
			"status": status,
			"completion_date": completion_date,
		}).insert(ignore_permissions=True)
		self._orders.append(doc.name)
		return doc

	def _last_test(self, container):
		value = frappe.db.get_value("Container", container, "last_test_date")
		return getdate(value) if value else None

	# --- uji di depo sendiri --------------------------------------------------
	def test_completed_periodic_test_stamps_the_master(self):
		c = self._container("LTDU1000001")
		self.assertIsNone(self._last_test(c))

		self._periodic_test(c, completion_date=add_days(today(), -3))

		self.assertEqual(self._last_test(c), getdate(add_days(today(), -3)))

	def test_unfinished_periodic_test_stamps_nothing(self):
		"""Antrean uji bukan uji. Order yang belum ditutup tidak menggeser tanggal apa pun."""
		c = self._container("LTDU1000002")

		self._periodic_test(c, completion_date=add_days(today(), -3), status="In Progress")

		self.assertIsNone(self._last_test(c))

	def test_ordinary_repair_never_stamps(self):
		c = self._container("LTDU1000003")
		doc = frappe.get_doc({
			"doctype": "Repair Order",
			"container": c,
			"job_type": "Repair",
			"status": "Completed",
			"completion_date": today(),
		}).insert(ignore_permissions=True)
		self._orders.append(doc.name)

		self.assertIsNone(self._last_test(c))

	def test_older_test_does_not_overwrite_a_newer_one(self):
		"""Order yang dibackdate — atau uji luar yang diketik belakangan — tidak boleh kalah
		oleh stempel yang lebih tua. Hanya yang LEBIH BARU yang menang."""
		c = self._container("LTDU1000004")
		set_last_test_date(c, add_days(today(), -10))

		self._periodic_test(c, completion_date=add_days(today(), -100))

		self.assertEqual(self._last_test(c), getdate(add_days(today(), -10)))

	def test_newer_test_wins_over_a_typed_one(self):
		c = self._container("LTDU1000005")
		set_last_test_date(c, add_days(today(), -100))

		self._periodic_test(c, completion_date=add_days(today(), -1))

		self.assertEqual(self._last_test(c), getdate(add_days(today(), -1)))

	# --- uji di luar depo -----------------------------------------------------
	def test_typed_date_lands_on_the_master(self):
		c = self._container("LTDU1000006")

		out = set_last_test_date(c, "2024-03-11")

		self.assertEqual(out["last_test_date"], "2024-03-11")
		self.assertEqual(self._last_test(c), getdate("2024-03-11"))

	def test_future_date_is_refused(self):
		c = self._container("LTDU1000007")

		with self.assertRaises(frappe.ValidationError):
			set_last_test_date(c, add_days(today(), 1))

		self.assertIsNone(self._last_test(c))

	def test_date_before_the_tank_was_built_is_refused(self):
		"""Salah ketik tahun yang paling sering: uji yang jatuh sebelum tank-nya ada."""
		c = self._container("LTDU1000008", manufacture_date="2019-05-01")

		with self.assertRaises(frappe.ValidationError):
			set_last_test_date(c, "2009-05-01")

		self.assertIsNone(self._last_test(c))

	def test_empty_date_is_refused(self):
		"""Mengosongkan tidak lewat sini — itu keputusan master, tempatnya form Container."""
		c = self._container("LTDU1000009")
		set_last_test_date(c, "2024-03-11")

		with self.assertRaises(frappe.ValidationError):
			set_last_test_date(c, "")

		self.assertEqual(self._last_test(c), getdate("2024-03-11"))
