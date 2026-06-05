"""Seed the 3rd-party Surveyor Company master OAK works with.

Idempotent: existing companies are skipped.
"""

from __future__ import annotations

import frappe

SURVEYORS = [
	{"surveyor_name": "PT Indomarine Survey", "contact_person": "Budi Setiawan", "email": "ops@indomarine.id", "specialty": "ISO Tank, General Container", "rating": 4.8},
	{"surveyor_name": "PT Surveyor Indonesia", "contact_person": "Hendra Wijaya", "email": "hendra@sucofindo.id", "specialty": "General Container, Tank", "rating": 4.6},
	{"surveyor_name": "PT Cipta Mitra Surveyor", "contact_person": "Lisa Anggraeni", "email": "lisa@ciptamitra.com", "specialty": "Reefer, Tank, M&R", "rating": 4.7},
]


def execute():
	seeded = 0
	for s in SURVEYORS:
		if frappe.db.exists("Surveyor Company", s["surveyor_name"]):
			continue
		frappe.get_doc({"doctype": "Surveyor Company", "is_active": 1, **s}).insert(ignore_permissions=True)
		seeded += 1
	frappe.db.commit()
	print(f"[container_depot] seed_surveyor_companies: ensured {seeded} surveyor(s).")
