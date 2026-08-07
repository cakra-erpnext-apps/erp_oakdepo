"""Booking Code: a single-use code printed as QR and given to a truck driver /
SST. Created (one per booking item) when an Container Booking is confirmed and
paid (or credit-approved for TOP). Codes do not expire — they stay usable until
consumed onto a bon / order.
"""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


def generate_code() -> str:
	"""Return a unique short token, used as both Booking Code name + QR payload."""
	for _ in range(8):
		token = hashlib.sha256(frappe.generate_hash().encode("utf-8")).hexdigest()[:12].upper()
		candidate = f"OAK-{token}"
		if not frappe.db.exists("Booking Code", candidate):
			return candidate
	# Vanishingly improbable, but fail loud if we somehow can't find a free one.
	frappe.throw("Could not generate a unique Booking Code; please retry.")


def qr_payload(code: str) -> str:
	return f"OAK|{code}"


class BookingCode(Document):
	def before_insert(self):
		if not self.code:
			self.code = generate_code()
		if not self.issued_at:
			self.issued_at = now_datetime()
		if not self.qr_image:
			self.qr_image = self._render_qr_image()

	def _render_qr_image(self) -> str | None:
		try:
			import qrcode
		except Exception:
			return None
		img = qrcode.make(qr_payload(self.code))
		buffered = BytesIO()
		img.save(buffered, format="PNG")
		b64 = base64.b64encode(buffered.getvalue()).decode("ascii")
		# Store inline as data URL so the form renders it without an extra File row.
		return f"data:image/png;base64,{b64}"

	def is_active(self) -> bool:
		return self.state == "Active"

	def is_expired(self) -> bool:
		# Booking Codes no longer expire; retained for callers/back-compat.
		return False
