"""ESS PWA profile endpoints — the operator's own avatar.

WHY THIS IS NOT ``frappe.handler.upload_file``. The obvious call is core's uploader with
``doctype=User, fieldname=user_image``, and it does not work here: it runs
``check_write_permission("User", <name>)``, and a field operator is a **Website User** whose
roles carry no DocPerm on User at all. The upload would 403 for exactly the people the PWA
exists for.

So the write is done with ``ignore_permissions`` — and to make that safe the target is not a
parameter. Both endpoints act on ``frappe.session.user`` and nothing else, so there is no
payload that can point them at somebody else's account.
"""

from __future__ import annotations

import io
import re

import frappe
from frappe import _

from container_depot.api import _require_authenticated_user

# Big enough for a phone frame that skipped compression, small enough that a bad upload on
# yard 3G fails fast instead of holding a worker's handset for a minute.
_MAX_BYTES = 8 * 1024 * 1024

# An avatar renders at 56 px. Anything past this is bytes nobody sees.
_MAX_EDGE = 512

# The PWA compresses before posting (``utils/photo.js``), but that compressor never throws —
# a frame it cannot decode is passed through untouched by design, because losing EIR evidence
# to a compression step is worse than a big upload. Which means an odd HEIC does arrive here,
# and the format check has to live on this side.
_ALLOWED = {
	"image/jpeg": "jpg",
	"image/png": "png",
	"image/webp": "webp",
}


def _decoded_content_type(content: bytes) -> str | None:
	"""What the BYTES are, not what the filename or the browser claims.

	A rename is all it takes to make ``script.svg`` look like ``avatar.jpg``, and the result
	is served from ``/files/`` on the site's own origin. Pillow reading a real raster is the
	check that cannot be talked around.
	"""
	from PIL import Image

	try:
		with Image.open(io.BytesIO(content)) as img:
			img.verify()
			fmt = (img.format or "").lower()
	except Exception:
		return None
	return {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(fmt)


@frappe.whitelist(methods=["POST"])
def set_profile_photo():
	"""POST (multipart, field ``file``) — replace the caller's own avatar.

	Returns ``{"user_image": <url>}``. The file is **public**: the avatar is rendered by a
	plain ``<img src>`` here and by the Desk navbar, and a private one would cost a
	permission round-trip on every render for a picture of somebody's face.

	The previous avatar is deleted, and only when it was one of ours (a File attached to this
	same user). Without that, every change would leave a copy on disk forever; with the
	attachment check, an admin who pointed ``user_image`` at a shared asset does not lose it.
	"""
	_require_authenticated_user()
	user = frappe.session.user

	# frappe.local.request, not frappe.request: the latter raises when there is no request
	# bound at all (a bench call, a test), and "no file posted" is the answer we want there.
	upload = (getattr(getattr(frappe.local, "request", None), "files", None) or {}).get("file")
	if not upload:
		frappe.throw(_("Tidak ada foto yang dikirim."), frappe.ValidationError)

	content = upload.stream.read()
	if not content:
		frappe.throw(_("File foto kosong."), frappe.ValidationError)
	if len(content) > _MAX_BYTES:
		frappe.throw(
			_("Foto terlalu besar (maks {0} MB).").format(_MAX_BYTES // (1024 * 1024)),
			frappe.ValidationError,
		)

	content_type = _decoded_content_type(content)
	if content_type not in _ALLOWED:
		frappe.throw(_("Format foto harus JPG, PNG, atau WEBP."), frappe.ValidationError)

	from frappe.utils.image import optimize_image

	content = optimize_image(content, content_type, max_width=_MAX_EDGE, max_height=_MAX_EDGE)

	previous = frappe.db.get_value("User", user, "user_image")

	# attached_to_field makes File.on_update write User.user_image itself — one code path for
	# the field and the attachment instead of two that can disagree.
	doc = frappe.get_doc({
		"doctype": "File",
		# frappe.scrub leaves "@" and "." in an email, which would put a second dot-segment
		# in front of the real extension.
		"file_name": f"avatar-{re.sub(r'[^a-z0-9]+', '-', user.lower()).strip('-')}.{_ALLOWED[content_type]}",
		"content": content,
		"attached_to_doctype": "User",
		"attached_to_name": user,
		"attached_to_field": "user_image",
		"folder": "Home/Attachments",
		"is_private": 0,
	}).insert(ignore_permissions=True)

	frappe.db.set_value("User", user, "user_image", doc.file_url, update_modified=False)
	_drop_previous_avatar(user, previous, doc.file_url)
	return {"user_image": doc.file_url}


@frappe.whitelist(methods=["POST"])
def remove_profile_photo():
	"""POST — clear the caller's avatar, falling the PWA back to their initials."""
	_require_authenticated_user()
	user = frappe.session.user
	previous = frappe.db.get_value("User", user, "user_image")
	frappe.db.set_value("User", user, "user_image", None, update_modified=False)
	_drop_previous_avatar(user, previous, None)
	return {"user_image": None}


def _drop_previous_avatar(user: str, previous: str | None, current: str | None) -> None:
	"""Delete the File the old ``user_image`` pointed at, if this user owned it.

	Best-effort: a stuck file is clutter, a failed profile save is a broken screen.
	"""
	if not previous or previous == current:
		return
	try:
		for name in frappe.get_all(
			"File",
			filters={
				"file_url": previous,
				"attached_to_doctype": "User",
				"attached_to_name": user,
			},
			pluck="name",
		):
			frappe.delete_doc("File", name, ignore_permissions=True, delete_permanently=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"drop previous avatar for {user}")
