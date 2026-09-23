"""Server-side autosave for PWA forms that have no draft document of their own.

EIR, Cleaning and M&R autosave into their own draft document. Letak Tank and the lowering step
write a record in ONE press, so there is nothing to save into until that press — and a
half-filled form (photos already taken) was lost when the page closed. This keeps it: one
``PWA Draft`` row per user per form key, restored when the form opens, deleted when it is sent.
"""

from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe import _

from container_depot.api import _require_authenticated_user

DRAFT = "PWA Draft"
_KEY = re.compile(r"^[a-z_]+:[\w.\-]{1,140}$")
_MAX = 64 * 1024


def _name(key: str) -> str:
	if not key or not _KEY.match(key):
		frappe.throw(_("Draft key tidak valid."))
	return hashlib.sha1(f"{frappe.session.user}::{key}".encode()).hexdigest()[:20]


@frappe.whitelist(methods=["GET"])
def draft_get(key=None):
	_require_authenticated_user()
	data = frappe.db.get_value(DRAFT, _name(key), "data")
	return json.loads(data) if data else None


@frappe.whitelist(methods=["POST"])
def draft_save(key=None, data=None):
	_require_authenticated_user()
	name = _name(key)
	if not isinstance(data, str):
		data = json.dumps(data)
	if len(data) > _MAX:
		frappe.throw(_("Draft terlalu besar."))
	if frappe.db.exists(DRAFT, name):
		frappe.db.set_value(DRAFT, name, "data", data)
	else:
		doc = frappe.new_doc(DRAFT)
		doc.name = name
		doc.update({"user": frappe.session.user, "draft_key": key, "data": data})
		doc.db_insert()
	return {"success": True}


@frappe.whitelist(methods=["POST"])
def draft_clear(key=None):
	_require_authenticated_user()
	frappe.db.delete(DRAFT, {"name": _name(key)})
	return {"success": True}
