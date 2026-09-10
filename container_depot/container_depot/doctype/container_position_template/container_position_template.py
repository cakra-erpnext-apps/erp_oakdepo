"""Posisi yang sering dipakai di satu depot — daftar pendek di balik form Posisi Tank.

Milik DEPOT, bukan milik orang yang membuatnya. Semua petugas depot itu melihat daftar yang
sama, dan itu justru gunanya: kalau tiap orang menulis bay yang sama dengan ejaan sendiri
("B4-R2", "b4 r2", "Bay 4 baris 2"), pencarian posisi berhenti bisa dipercaya dan dua orang
yang berdiri di tumpukan yang sama menulis dua jawaban yang berbeda.

Template TIDAK memegang riwayat. Menghapus satu template tidak mengubah satu pun posisi yang
sudah tercatat dengan tulisan itu — pencatatan adalah dokumen tersendiri (``Container
Position``) yang menyimpan teksnya sendiri, bukan sebuah link ke sini. Itu sengaja: daftar
pilihan boleh dirapikan kapan saja tanpa menulis ulang sejarah yard.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ContainerPositionTemplate(Document):
	def validate(self):
		self.label = (self.label or "").strip()
		if not self.label:
			frappe.throw(_("Posisi tidak boleh kosong."))
		self._no_duplicate()

	def _no_duplicate(self):
		"""Satu tulisan, satu baris, per depot.

		Dicek tanpa memperhatikan besar-kecil huruf: "Bay 1" dan "bay 1" adalah bay yang sama
		bagi orang yang berdiri di depannya, dan dua baris kembar di daftar pilihan cuma
		membuat dua orang memilih yang berbeda.
		"""
		twin = frappe.db.sql(
			"""select name from `tabContainer Position Template`
			    where depot = %(depot)s and lower(label) = %(label)s and name != %(name)s limit 1""",
			{"depot": self.depot, "label": self.label.lower(), "name": self.name or ""},
		)
		if twin:
			frappe.throw(_("Template “{0}” sudah ada di depot ini.").format(self.label))
