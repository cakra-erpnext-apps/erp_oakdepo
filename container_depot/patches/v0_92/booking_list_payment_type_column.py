"""Kolom Payment Type di daftar Container Booking — juga untuk site yang kolomnya sudah dipilih.

Menandai sebuah field ``in_list_view`` cuma mengatur kolom BAWAAN. Begitu seseorang pernah
memilih kolom lewat "Pick Columns", pilihan itu tersimpan sebagai ``List View Settings`` untuk
doctype-nya dan sejak itu dialah yang menentukan — jadi field baru tidak akan pernah muncul di
site yang sudah pernah menyetel kolomnya, dan kelihatan seperti perubahannya tidak jalan.

Patch ini menyisipkan Payment Type tepat sebelum Payment Status pada setelan itu, kalau memang
ada. Idempoten, dan tidak menyentuh kolom lain yang sudah dipilih orang.
"""

from __future__ import annotations

import json

import frappe

DOCTYPE = "Container Booking"


def execute():
	if not frappe.db.exists("List View Settings", DOCTYPE):
		return  # belum pernah disetel: `in_list_view` di doctype yang berlaku

	doc = frappe.get_doc("List View Settings", DOCTYPE)
	fields = json.loads(doc.fields or "[]")
	if any(f.get("fieldname") == "payment_type" for f in fields):
		return

	at = next((i for i, f in enumerate(fields) if f.get("fieldname") == "payment_status"), len(fields))
	fields.insert(at, {"fieldname": "payment_type", "label": "Payment Type"})
	doc.fields = json.dumps(fields)
	doc.save(ignore_permissions=True)
