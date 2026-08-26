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


class StorageCharge(Document):
	pass
