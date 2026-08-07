"""Depot master — physical OAK depot/branch (Surabaya, OAK Medan / KIM 11).

PRD v0.2 §3: multi-depo operations. We model the depot as its own master
(rather than reusing ERPNext Branch, whose semantics are HR cost-centre) and
hang a ``depot`` Link off the core operational entities for data separation +
per-depot reporting. Inter-depot transfer is explicitly out of scope for v1.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class Depot(Document):
	pass


def get_default_depot() -> str | None:
	"""Return a sensible default depot name for backfills / new records.

	Prefers the single active depot when there is exactly one; otherwise None
	so callers leave the field blank rather than guessing.
	"""
	active = frappe.get_all("Depot", filters={"is_active": 1}, pluck="name")
	if len(active) == 1:
		return active[0]
	return None
