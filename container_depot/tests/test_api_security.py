"""Security regression tests for ``container_depot.api``.

Covers the Phase 1 (PRO-OPS-08) hardening rules in :mod:`container_depot.api`:

- Parameterized queries / input validation block SQL-injection-shaped payloads.
- State-changing endpoints reject Guest callers even via direct Python call.
- ``handle_webhook`` requires a valid HMAC ``X-Signature`` over the raw body.
- ``validate_qr`` accepts both a bare Booking Code and the ``OAK|...`` QR payload.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot import api as cdapi
from container_depot.tests._booking_helpers import make_booking_code
from container_depot.tests.test_api import ensure_test_customer


TEST_SECRET = "test-webhook-secret"
SEC_CUSTOMER = "Security Test Customer"
SEC_CONTAINER_NO = "SECU1234560"


def _make_request(body: bytes, signature: str | None):
	"""Build a minimal stand-in for ``frappe.local.request``."""
	headers = {}
	if signature is not None:
		headers["X-Signature"] = signature

	class _Headers(dict):
		def get(self, key, default=None):
			return super().get(key, super().get(key.lower(), default))

	h = _Headers({k.lower(): v for k, v in headers.items()})
	h.update(headers)
	return SimpleNamespace(
		get_data=lambda cache=True: body,
		headers=h,
	)


class TestApiSecurity(FrappeTestCase):
	def _active_code(self):
		"""Create an Active Booking Code within the test's transaction."""
		return make_booking_code(
			customer=ensure_test_customer(SEC_CUSTOMER),
			container_no=SEC_CONTAINER_NO,
			direction="Tank Out",
		)

	# ------------------------------------------------------------------
	# Input validation / parameterized lookup
	# ------------------------------------------------------------------

	def test_validate_qr_rejects_sql_injection_attempt(self):
		"""SQLi-shaped payloads must fall out at input validation, not run."""
		for payload in [
			"' OR 1=1 --",
			"%' UNION SELECT * FROM tabUser --",
			"OAK-FOO'; DROP TABLE `tabBooking Code` --",
			"' OR '1'='1",
		]:
			result = cdapi.validate_qr(payload)
			self.assertFalse(result["valid"], f"payload {payload!r} should be invalid")
			self.assertIn("error", result)

	def test_validate_qr_accepts_bare_booking_code(self):
		code = self._active_code()
		result = cdapi.validate_qr(code.code)
		self.assertTrue(result["valid"])
		self.assertEqual(result["booking_code"], code.name)

	def test_validate_qr_accepts_oak_pipe_payload(self):
		code = self._active_code()
		result = cdapi.validate_qr(f"OAK|{code.code}")
		self.assertTrue(result["valid"])
		self.assertEqual(result["booking_code"], code.name)

	def test_validate_qr_rejects_malformed_oak_payload(self):
		result = cdapi.validate_qr("OAK|")
		self.assertFalse(result["valid"])

	def test_normalize_container_no_accepts_non_iso_length(self):
		# Length is no longer enforced — real depot data carries short / non-ISO numbers,
		# so only presence + a safe character set are required (not an 11-char shape).
		self.assertEqual(cdapi._normalize_container_no("STLU1234"), "STLU1234")

	def test_normalize_container_no_strips_and_uppercases(self):
		self.assertEqual(cdapi._normalize_container_no(" stlu123456-7 "), "STLU123456-7")

	def test_normalize_container_no_rejects_special_chars(self):
		with self.assertRaises(frappe.ValidationError):
			cdapi._normalize_container_no("STLU%23456-7")
		with self.assertRaises(frappe.ValidationError):
			cdapi._normalize_container_no("STLU'12345-7")

	def test_parse_booking_code_format(self):
		with self.assertRaises(frappe.ValidationError):
			cdapi._parse_booking_code_payload("NOT-A-CODE")
		self.assertEqual(cdapi._parse_booking_code_payload("oak-abc123"), "OAK-ABC123")

	# ------------------------------------------------------------------
	# Auth: state-changing endpoints must reject Guest
	# ------------------------------------------------------------------

	def _as_guest(self, fn):
		original = frappe.session.user
		try:
			frappe.set_user("Guest")
			fn()
		finally:
			frappe.set_user(original)

	def test_register_gate_entry_rejects_guest(self):
		def call():
			with self.assertRaises(frappe.PermissionError):
				cdapi.register_gate_entry(
					booking_code="OAK-ABC123", container_no="STLU123456-7"
				)
		self._as_guest(call)

	def test_update_container_location_rejects_guest(self):
		def call():
			with self.assertRaises(frappe.PermissionError):
				cdapi.update_container_location(
					container_no="STLU123456-7", yard_zone="Storage_Yard_A"
				)
		self._as_guest(call)

	def test_upload_inspection_evidence_rejects_guest(self):
		def call():
			with self.assertRaises(frappe.PermissionError):
				cdapi.upload_inspection_evidence(
					container_no="STLU123456-7",
					photos=[{"view": "Front"}],
				)
		self._as_guest(call)

	def test_handle_webhook_rejects_guest(self):
		def call():
			with self.assertRaises(frappe.PermissionError):
				cdapi.handle_webhook(platform="whatsapp", message="hi")
		self._as_guest(call)

	# ------------------------------------------------------------------
	# Auth: register_gate_entry input validation runs BEFORE DB writes
	# ------------------------------------------------------------------

	def test_register_gate_entry_validates_container_no(self):
		# Length is no longer checked, so an invalid input must fail the character-set
		# guard instead (a '%' is rejected) — input validation still runs before DB writes.
		with self.assertRaises(frappe.ValidationError):
			cdapi.register_gate_entry(
				booking_code="OAK-ABC123", container_no="BAD%CHAR"
			)

	def test_register_gate_entry_validates_booking_code(self):
		with self.assertRaises(frappe.ValidationError):
			cdapi.register_gate_entry(
				booking_code="not-a-code", container_no="STLU123456-7"
			)

	# ------------------------------------------------------------------
	# Webhook signature: pure helper
	# ------------------------------------------------------------------

	def test_verify_webhook_signature_accepts_valid(self):
		body = b'{"platform":"whatsapp"}'
		sig = hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()
		self.assertTrue(cdapi._verify_webhook_signature(body, sig, TEST_SECRET))
		self.assertTrue(cdapi._verify_webhook_signature(body, f"sha256={sig}", TEST_SECRET))

	def test_verify_webhook_signature_rejects_wrong(self):
		body = b'{"platform":"whatsapp"}'
		self.assertFalse(
			cdapi._verify_webhook_signature(body, "deadbeef" * 8, TEST_SECRET)
		)
		self.assertFalse(cdapi._verify_webhook_signature(body, "", TEST_SECRET))
		self.assertFalse(cdapi._verify_webhook_signature(body, None, TEST_SECRET))
		self.assertFalse(cdapi._verify_webhook_signature(body, "abc", ""))

	# ------------------------------------------------------------------
	# Webhook signature: enforcement inside an HTTP-like context
	# ------------------------------------------------------------------

	def _set_request(self, body: bytes, signature: str | None):
		req = _make_request(body, signature)
		frappe.local.request = req

	def _clear_request(self):
		if hasattr(frappe.local, "request"):
			try:
				del frappe.local.request
			except Exception:
				frappe.local.request = None

	def test_handle_webhook_rejects_missing_signature(self):
		original_secret = frappe.conf.get("container_depot_webhook_secret")
		frappe.local.conf["container_depot_webhook_secret"] = TEST_SECRET
		try:
			body = b'{"platform":"whatsapp","message":"hello"}'
			self._set_request(body, signature=None)
			with self.assertRaises(frappe.AuthenticationError):
				cdapi.handle_webhook(platform="whatsapp", message="hello")
		finally:
			self._clear_request()
			if original_secret is None:
				frappe.local.conf.pop("container_depot_webhook_secret", None)
			else:
				frappe.local.conf["container_depot_webhook_secret"] = original_secret

	def test_handle_webhook_rejects_bad_signature(self):
		original_secret = frappe.conf.get("container_depot_webhook_secret")
		frappe.local.conf["container_depot_webhook_secret"] = TEST_SECRET
		try:
			body = b'{"platform":"whatsapp","message":"hello"}'
			self._set_request(body, signature="sha256=" + "0" * 64)
			with self.assertRaises(frappe.AuthenticationError):
				cdapi.handle_webhook(platform="whatsapp", message="hello")
		finally:
			self._clear_request()
			if original_secret is None:
				frappe.local.conf.pop("container_depot_webhook_secret", None)
			else:
				frappe.local.conf["container_depot_webhook_secret"] = original_secret

	def test_handle_webhook_accepts_valid_signature(self):
		original_secret = frappe.conf.get("container_depot_webhook_secret")
		frappe.local.conf["container_depot_webhook_secret"] = TEST_SECRET
		try:
			payload = {"platform": "whatsapp", "message": "help"}
			body = json.dumps(payload).encode("utf-8")
			sig = hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()
			self._set_request(body, signature=f"sha256={sig}")
			result = cdapi.handle_webhook(platform="whatsapp", message="help")
			self.assertTrue(result.get("success"))
			self.assertEqual(result.get("intent"), "help")
		finally:
			self._clear_request()
			if original_secret is None:
				frappe.local.conf.pop("container_depot_webhook_secret", None)
			else:
				frappe.local.conf["container_depot_webhook_secret"] = original_secret

	def test_handle_webhook_rejects_oversize_body(self):
		original_secret = frappe.conf.get("container_depot_webhook_secret")
		frappe.local.conf["container_depot_webhook_secret"] = TEST_SECRET
		try:
			body = b"x" * (cdapi.MAX_WEBHOOK_BODY_BYTES + 1)
			sig = hmac.new(TEST_SECRET.encode(), body, hashlib.sha256).hexdigest()
			self._set_request(body, signature=f"sha256={sig}")
			with self.assertRaises(frappe.ValidationError):
				cdapi.handle_webhook(platform="whatsapp", message="x")
		finally:
			self._clear_request()
			if original_secret is None:
				frappe.local.conf.pop("container_depot_webhook_secret", None)
			else:
				frappe.local.conf["container_depot_webhook_secret"] = original_secret

	# ------------------------------------------------------------------
	# Service role created by install/migrate
	# ------------------------------------------------------------------

	def test_sst_service_role_exists(self):
		self.assertTrue(
			frappe.db.exists("Role", "Container Depot SST Service"),
			"SST service role must be created by install/after_migrate",
		)


if __name__ == "__main__":
	unittest.main()
