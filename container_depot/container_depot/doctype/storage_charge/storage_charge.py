"""One record per depot visit — the storage BILLING ledger.

The physical facts of a visit (masuk, keluar) stay where they are recorded: the Gate
Entry. This document is what the depot did about them — how many days were billed, up to
when, and whether the visit is settled. It exists because a single watermark per container
could not hold that:

    Kunjungan Juli belum ditagih, kunjungan Agustus sudah.

``Container.storage_billed_until`` is one date, so billing the August visit made it claim
July was billed too, and six days quietly became unbillable. A record per visit carries its
own ``billed_until``, so an older unbilled visit cannot be swallowed by a newer billed one.

Everything on it is written by :mod:`container_depot.storage_charge` — the whole document
is read-only in the UI. It is a ledger, not a form.
"""

from __future__ import annotations

from frappe.model.document import Document
from frappe.model.naming import append_number_if_name_exists


class StorageCharge(Document):
	def autoname(self):
		"""``STG-<tank>-<tanggal masuk>``, numbered when the day holds more than one visit.

		The date alone is not a name. A tank can leave and come back the same day, and a
		visit is identified by its Gate Entry — so one container/day can legitimately carry
		several visits, and a plain ``format:`` naming rule made the second one collide with
		the first instead of opening its own row:

		    Duplicate entry 'STG-MCSUB0X0002-2026-09-02' for key 'PRIMARY'

		The suffix counts *visits*, not attempts. A re-sync finds the visit's row by key
		(:func:`container_depot.storage_charge._key`) long before it would be named, so
		re-running never walks the number forward.
		"""
		self.name = append_number_if_name_exists(
			self.doctype, f"STG-{self.container}-{self.date_in_key}"
		)
