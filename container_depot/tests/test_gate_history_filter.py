"""Riwayat Gate yang disaring arah + tanggal — jalan yang dibuka kartu Beranda.

Kartu "Tank masuk" / "Tank keluar" menautkan ke ``/gate/history`` dengan arah dan hari yang
sama dengan angka yang barusan dibaca operator, jadi ``list_gate_history`` harus menjawab
dengan baris yang persis itu: arah dibaca dari cap waktu mana yang terisi, bukan dari sebuah
field arah.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, today

from container_depot.container_depot.gate import list_gate_history

PREFIX = "GHFILT"


def _entry(suffix, **stamps):
	doc = frappe.get_doc({
		"doctype": "Gate Entry",
		"container_no": f"{PREFIX}{suffix}",
		"status": "Active",
		**stamps,
	}).insert(ignore_permissions=True)
	return doc.name


class TestGateHistoryFilter(FrappeTestCase):
	def setUp(self):
		now = now_datetime()
		self.today_in = _entry("IN", gate_in_timestamp=now)
		self.today_out = _entry("OUT", gate_in_timestamp=add_days(now, -3), gate_out_timestamp=now)
		self.old_in = _entry("OLD", gate_in_timestamp=add_days(now, -7))

	def tearDown(self):
		for name in (self.today_in, self.today_out, self.old_in):
			frappe.delete_doc("Gate Entry", name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _tanks(self, **kwargs):
		rows = list_gate_history(search=PREFIX, page_length=50, **kwargs)["items"]
		return {r.container_no for r in rows}

	def test_no_filter_lists_everything(self):
		self.assertEqual(self._tanks(), {f"{PREFIX}IN", f"{PREFIX}OUT", f"{PREFIX}OLD"})

	def test_in_today(self):
		# Yang masuk hari ini saja — yang masuk seminggu lalu tidak ikut, dan tank yang
		# hari ini KELUAR pun tidak: cap masuknya tiga hari lalu.
		self.assertEqual(self._tanks(direction="in", day="today"), {f"{PREFIX}IN"})

	def test_out_today(self):
		self.assertEqual(self._tanks(direction="out", day="today"), {f"{PREFIX}OUT"})

	def test_direction_without_day(self):
		# Tanpa tanggal: semua yang pernah lewat pintu itu, berapa pun umurnya.
		self.assertEqual(self._tanks(direction="in"), {f"{PREFIX}IN", f"{PREFIX}OUT", f"{PREFIX}OLD"})
		self.assertEqual(self._tanks(direction="out"), {f"{PREFIX}OUT"})

	def test_explicit_date(self):
		self.assertEqual(self._tanks(direction="in", day=today()), {f"{PREFIX}IN"})
		self.assertEqual(self._tanks(direction="in", day=add_days(today(), -7)), {f"{PREFIX}OLD"})

	def test_junk_direction_is_ignored(self):
		# "undefined" dari klien tidak boleh menyembunyikan seluruh riwayat.
		self.assertEqual(self._tanks(direction="undefined", day="undefined"), self._tanks())

	def test_day_without_direction_uses_creation(self):
		# Saringan Tanggal di Riwayat Gate tanpa arah: tanggal voucher dibuat (semua dibuat hari ini).
		self.assertEqual(self._tanks(day="today"), self._tanks())
		self.assertEqual(self._tanks(day=add_days(today(), -1)), set())

	def test_sort_follows_filtered_stamp(self):
		rows = list_gate_history(search=PREFIX, page_length=50, direction="in", sort="oldest")["items"]
		self.assertEqual([r.container_no for r in rows], [f"{PREFIX}OLD", f"{PREFIX}OUT", f"{PREFIX}IN"])
