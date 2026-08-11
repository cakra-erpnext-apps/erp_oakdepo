"""Tests for the PWA profile photo (``ess.profile``).

The endpoint writes with ``ignore_permissions`` — a field operator is a Website User with no
DocPerm on User, so core's uploader refuses them. That makes two things load-bearing and
worth pinning: the target is always ``frappe.session.user`` and never a parameter, and what
lands on disk is a real raster rather than whatever the filename claimed.
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess import profile

PREFIX = "pfoto"


def _png(size=(40, 40), color=(200, 90, 20)) -> bytes:
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", size, color).save(buf, format="PNG")
	return buf.getvalue()


class _Request:
	"""Stands in for a werkzeug request. ``host`` is here because File.save_file reaches for
	it through get_url() on the way to writing the bytes — not because this code reads it."""

	host = None

	def __init__(self, files):
		self.files = files


def _post(content: bytes | None, filename="avatar.png"):
	"""Run the endpoint as if a multipart POST had carried ``content``."""
	from werkzeug.datastructures import FileStorage

	original = getattr(frappe.local, "request", None)
	files = {}
	if content is not None:
		files["file"] = FileStorage(stream=io.BytesIO(content), filename=filename)
	frappe.local.request = _Request(files)
	try:
		return profile.set_profile_photo()
	finally:
		frappe.local.request = original


class TestProfilePhoto(FrappeTestCase):
	def setUp(self):
		self.email = f"{PREFIX}-operator@example.com"
		if not frappe.db.exists("User", self.email):
			frappe.get_doc({
				"doctype": "User",
				"email": self.email,
				"first_name": "Foto",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		self._original = frappe.session.user
		frappe.set_user(self.email)

	def tearDown(self):
		frappe.set_user(self._original)
		# delete_doc, not db.delete: the rollback FrappeTestCase does covers the rows, not the
		# bytes these tests wrote under public/files. Only File.on_trash removes those.
		for name in frappe.get_all(
			"File",
			filters={"attached_to_doctype": "User", "attached_to_name": self.email},
			pluck="name",
		):
			frappe.delete_doc("File", name, ignore_permissions=True, delete_permanently=True, force=True)
		frappe.db.delete("User", {"name": self.email})

	def _user_image(self):
		return frappe.db.get_value("User", self.email, "user_image")

	def test_a_photo_lands_on_the_caller_and_nowhere_else(self):
		res = _post(_png())
		self.assertTrue(res["user_image"])
		self.assertEqual(self._user_image(), res["user_image"])

		files = frappe.get_all(
			"File",
			filters={"file_url": res["user_image"]},
			fields=["attached_to_doctype", "attached_to_name", "is_private"],
		)
		self.assertEqual(len(files), 1)
		self.assertEqual(files[0].attached_to_doctype, "User")
		self.assertEqual(files[0].attached_to_name, self.email)
		# Public on purpose: rendered by a plain <img src> here and in the Desk navbar.
		self.assertEqual(files[0].is_private, 0)

	def test_bytes_decide_the_format_not_the_filename(self):
		"""Renaming a script to .png is the whole attack, and the file would be served from
		the site's own origin under /files/."""
		with self.assertRaises(frappe.ValidationError):
			_post(b"<svg onload=alert(1)></svg>", filename="avatar.png")
		self.assertFalse(self._user_image())

	def test_an_empty_post_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_post(None)
		with self.assertRaises(frappe.ValidationError):
			_post(b"")

	def test_oversize_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_post(b"\x89PNG\r\n\x1a\n" + b"0" * (profile._MAX_BYTES + 1))
		self.assertFalse(self._user_image())

	def test_replacing_does_not_leave_the_old_file_behind(self):
		first = _post(_png(color=(10, 10, 10)))["user_image"]
		second = _post(_png(color=(240, 240, 240)))["user_image"]
		self.assertNotEqual(first, second)
		self.assertEqual(self._user_image(), second)
		self.assertFalse(
			frappe.db.exists("File", {"file_url": first}),
			"every photo change would otherwise leave a copy on disk forever",
		)

	def test_removing_clears_the_field_and_the_file(self):
		url = _post(_png())["user_image"]
		res = profile.remove_profile_photo()
		self.assertIsNone(res["user_image"])
		self.assertFalse(self._user_image())
		self.assertFalse(frappe.db.exists("File", {"file_url": url}))

	def test_a_shared_asset_someone_pointed_user_image_at_is_not_deleted(self):
		"""The cleanup is scoped to files attached to THIS user — an admin who set the avatar
		to a shared logo must not lose the logo when the operator changes their photo."""
		frappe.db.set_value("User", self.email, "user_image", "/files/some-shared-logo.png")
		_post(_png())
		# Nothing was attached to the user, so there was nothing of ours to delete and no
		# stray delete of the shared URL either.
		self.assertFalse(frappe.db.exists("File", {"file_url": "/files/some-shared-logo.png"}))

	def test_context_hands_the_photo_to_the_pwa(self):
		from container_depot.ess.context import get_user_context

		self.assertIsNone(get_user_context()["user_image"])
		url = _post(_png())["user_image"]
		self.assertEqual(get_user_context()["user_image"], url)
