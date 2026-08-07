"""Inspection Damage Code master — baku OAK damage catalogue (PRD v0.2 §1).

Replaces the free-text ``damage_type`` Select on Inspection Damage Entry with a controlled
master so EIRs reference standard OAK codes. The authoritative code list comes
from ``Eir_new_Rev_3.xlsx``; the seed patch ships a baseline that must be
extended from that workbook.
"""

from __future__ import annotations

from frappe.model.document import Document


class InspectionDamageCode(Document):
	pass
