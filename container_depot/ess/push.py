"""Web Push (VAPID) for the depot PWA — the half of notifications that works with the
app closed.

``container_depot.notify`` already decides *who* should hear about a depot event: it
filters by branch scope and by the roles the event is routed to, then writes one
Notification Log row per recipient. That row lights up the Desk bell and the PWA bell —
but only for someone who happens to be looking. A yard operator with the phone in their
pocket learns nothing until they next open the app.

This module is the delivery leg. It takes the recipient list ``notify`` already computed
and pushes the same subject to every browser those people registered, so the phone rings
the way any other app would.

WHY SELF-HOSTED VAPID AND NOT FRAPPE'S PUSH
-------------------------------------------
``frappe.push_notification`` routes through FCM via a separate ``notification_relay``
service, which means a Frappe Cloud account (or a relay to self-host) plus a Firebase
project. This depot runs on its own box behind Caddy; VAPID needs neither. The browser
hands us an endpoint URL, we sign a JWT with a keypair that lives in ``site_config`` and
POST to it. No third party sees depot traffic.

WHAT THIS DOES NOT DO
---------------------
Nothing here decides recipients — do not add filtering. Two places choosing who gets told
is how a routing change ends up half-applied.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

SUBSCRIPTION_DOCTYPE = "Depot Push Subscription"

# Endpoints go stale constantly: an uninstalled PWA, a cleared browser, an expired FCM
# registration. The push service tells us so with these, and the row is worthless after.
_GONE_STATUS = (404, 410)

# A push service that is merely unreachable (network blip, 5xx) says nothing about the
# subscription. Only drop a row after it has failed this many times in a row, so one bad
# afternoon does not unsubscribe the whole yard.
_MAX_FAILURES = 10


def _keys() -> tuple[str, str] | None:
	"""VAPID (public, private) from site_config, or None when push is not set up.

	Absent keys are a normal state, not an error: a site that never ran
	``generate_vapid_keys`` simply has no push. Callers fall back to the bell.
	"""
	public = frappe.conf.get("depot_vapid_public_key")
	private = frappe.conf.get("depot_vapid_private_key")
	return (public, private) if public and private else None


def _subject() -> str:
	"""VAPID `sub` claim — a contact for the push service to reach if we misbehave.

	Must be a ``mailto:`` link. The spec also allows an https URL, but py_vapid rejects
	anything else outright ("Missing 'sub' from claims"), so a site URL here silently
	kills every push. Override with ``depot_vapid_subject`` in site_config.
	"""
	configured = frappe.conf.get("depot_vapid_subject")
	if configured:
		return configured if configured.startswith("mailto:") else f"mailto:{configured}"
	email = frappe.db.get_value("User", "Administrator", "email")
	if not email or "@" not in email:
		host = frappe.utils.get_url().split("//")[-1].split(":")[0]
		email = f"admin@{host}"
	return f"mailto:{email}"


def generate_vapid_keys(force: bool = False) -> str:
	"""Create the VAPID keypair and write it into site_config. Run once per site::

	    bench --site <site> execute container_depot.ess.push.generate_vapid_keys

	Idempotent — an existing keypair is kept unless ``force``, because regenerating it
	invalidates every subscription already handed out and silently stops every phone.
	"""
	from frappe.installer import update_site_config
	from py_vapid import Vapid

	if _keys() and not force:
		return frappe.conf.get("depot_vapid_public_key")

	vapid = Vapid()
	vapid.generate_keys()
	# The browser wants the raw public key, base64url with no padding; py_vapid hands both
	# halves back in that shape via its *_key_urlsafe helpers.
	public = vapid.public_key_urlsafe.decode() if hasattr(vapid, "public_key_urlsafe") else None
	private = vapid.private_key_urlsafe.decode() if hasattr(vapid, "private_key_urlsafe") else None
	if not (public and private):
		public, private = _export_keys(vapid)

	update_site_config("depot_vapid_public_key", public, validate=False)
	update_site_config("depot_vapid_private_key", private, validate=False)
	print(f"VAPID public key: {public}")
	return public


def _export_keys(vapid) -> tuple[str, str]:
	"""Fallback export for py_vapid builds without the ``*_urlsafe`` properties."""
	import base64

	from cryptography.hazmat.primitives import serialization

	raw_public = vapid.public_key.public_bytes(
		serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
	)
	raw_private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
	b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
	return b64(raw_public), b64(raw_private)


# ---------------------------------------------------------------------------
# PWA-facing endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_config():
	"""GET — the public key the browser needs to subscribe, plus whether push is on."""
	from container_depot.api import _require_authenticated_user

	_require_authenticated_user()
	keys = _keys()
	return {"success": True, "enabled": bool(keys), "public_key": keys[0] if keys else None}


@frappe.whitelist(methods=["POST"])
def subscribe(subscription):
	"""POST — register (or refresh) this browser for the logged-in user.

	Upsert by endpoint hash: browsers hand back the same endpoint on every app load, and a
	re-subscribe after a permission re-grant must not pile up duplicate rows that would
	each ring the same phone.
	"""
	from container_depot.api import _require_authenticated_user
	from container_depot.container_depot.doctype.depot_push_subscription.depot_push_subscription import (
		hash_endpoint,
	)

	_require_authenticated_user()
	sub = json.loads(subscription) if isinstance(subscription, str) else (subscription or {})
	endpoint = (sub.get("endpoint") or "").strip()
	keys = sub.get("keys") or {}
	if not (endpoint and keys.get("p256dh") and keys.get("auth")):
		frappe.throw(frappe._("Langganan notifikasi tidak lengkap."))

	values = {
		"user": frappe.session.user,
		"endpoint": endpoint,
		"p256dh": keys["p256dh"],
		"auth": keys["auth"],
		"user_agent": (frappe.get_request_header("User-Agent") or "")[:500],
		"enabled": 1,
		"failure_count": 0,
		"last_used": now_datetime(),
	}

	name = frappe.db.exists(SUBSCRIPTION_DOCTYPE, {"endpoint_hash": hash_endpoint(endpoint)})
	if name:
		doc = frappe.get_doc(SUBSCRIPTION_DOCTYPE, name)
		# A shared handset changes hands between shifts; the endpoint stays the same but
		# the person behind it does not. Re-point the row rather than leaving the previous
		# operator subscribed to this phone.
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": SUBSCRIPTION_DOCTYPE, **values})
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "name": doc.name}


@frappe.whitelist(methods=["POST"])
def unsubscribe(endpoint: str | None = None):
	"""POST — drop this browser's registration (user turned notifications off)."""
	from container_depot.api import _require_authenticated_user
	from container_depot.container_depot.doctype.depot_push_subscription.depot_push_subscription import (
		hash_endpoint,
	)

	_require_authenticated_user()
	filters = {"user": frappe.session.user}
	if endpoint:
		filters["endpoint_hash"] = hash_endpoint(endpoint)
	for name in frappe.get_all(SUBSCRIPTION_DOCTYPE, filters=filters, pluck="name"):
		frappe.delete_doc(SUBSCRIPTION_DOCTYPE, name, ignore_permissions=True, force=True)
	frappe.db.commit()
	return {"success": True}


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def push_to_users(users: list[str], *, title: str, body: str = "", url: str = "/depot", tag: str = ""):
	"""Queue a push for everyone in ``users``. Safe to call from a document hook.

	Enqueued, and ``after_commit``: talking to FCM/Mozilla takes network round-trips per
	device, and a gate submit must not wait on them — nor fire a notification for a
	transaction that then rolls back.
	"""
	if not users or not _keys():
		return
	try:
		frappe.enqueue(
			"container_depot.ess.push.deliver",
			queue="short",
			enqueue_after_commit=True,
			users=list(users),
			title=title,
			body=body,
			url=url,
			tag=tag,
		)
	except Exception:
		frappe.log_error(title="Depot push enqueue failed", message=frappe.get_traceback())


def deliver(users: list[str], title: str, body: str = "", url: str = "/depot", tag: str = ""):
	"""Background job — send one payload to every live subscription of every user."""
	keys = _keys()
	if not keys:
		return 0
	_public, private = keys

	rows = frappe.get_all(
		SUBSCRIPTION_DOCTYPE,
		filters={"user": ["in", users], "enabled": 1},
		fields=["name", "endpoint", "p256dh", "auth", "failure_count"],
		limit_page_length=0,
	)
	if not rows:
		return 0

	payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or "depot"})
	sent = 0
	for row in rows:
		if _send_one(row, payload, private):
			sent += 1
	frappe.db.commit()
	return sent


def _send_one(row, payload: str, private_key: str) -> bool:
	"""One device. Returns True on delivery; prunes or counts the failure otherwise."""
	from pywebpush import WebPushException, webpush

	try:
		webpush(
			subscription_info={
				"endpoint": row.endpoint,
				"keys": {"p256dh": row.p256dh, "auth": row.auth},
			},
			data=payload,
			vapid_private_key=private_key,
			vapid_claims={"sub": _subject()},
			timeout=10,
		)
	except WebPushException as e:
		status = getattr(getattr(e, "response", None), "status_code", None)
		if status in _GONE_STATUS:
			# The browser is gone for good — an uninstalled PWA or a cleared profile.
			frappe.delete_doc(SUBSCRIPTION_DOCTYPE, row.name, ignore_permissions=True, force=True)
			return False
		_count_failure(row)
		return False
	except Exception:
		_count_failure(row)
		frappe.log_error(title="Depot push send failed", message=frappe.get_traceback())
		return False

	frappe.db.set_value(
		SUBSCRIPTION_DOCTYPE,
		row.name,
		{"last_used": now_datetime(), "failure_count": 0},
		update_modified=False,
	)
	return True


def _count_failure(row) -> None:
	count = (row.failure_count or 0) + 1
	if count >= _MAX_FAILURES:
		frappe.delete_doc(SUBSCRIPTION_DOCTYPE, row.name, ignore_permissions=True, force=True)
		return
	frappe.db.set_value(
		SUBSCRIPTION_DOCTYPE, row.name, "failure_count", count, update_modified=False
	)
