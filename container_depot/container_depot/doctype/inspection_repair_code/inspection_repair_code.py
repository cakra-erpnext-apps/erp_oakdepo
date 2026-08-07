"""Inspection Repair Code master — baku OAK repair-action catalogue (PRD v0.2 §1).

Linked from Inspection Damage Entry so each recorded damage can carry a standard repair
action. Authoritative list comes from ``Eir_new_Rev_3.xlsx``; the seed patch
ships a generic baseline to extend.
"""

from __future__ import annotations

from frappe.model.document import Document


class InspectionRepairCode(Document):
	pass
