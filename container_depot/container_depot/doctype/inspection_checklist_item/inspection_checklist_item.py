"""Inspection Checklist Item master — the fixed Area→Item taxonomy of the OAK EIR grid.

50 rows in 10 areas, verbatim from ``Eir_new_Rev_3.xlsx``. ``sequence`` (1-50) is
the canonical identity; ``printed_no`` keeps the workbook's printed number as-is
(duplicates 32 & 46 are real document facts, not normalised). Seeded idempotently
by ``patches/v0_25/seed_eir_checklist.py``.
"""

from __future__ import annotations

from frappe.model.document import Document


class InspectionChecklistItem(Document):
	pass
