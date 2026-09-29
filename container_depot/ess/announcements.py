"""Manual announcements — one Frappe **Note** reaches the Desk and the depot PWA.

No doctype of our own: Frappe's Note already is the announcement. An admin writes one in the
Desk (Note → Public + Notify On Login, optional Expire Notification On — Frappe defaults it
to a week), and:

* the Desk shows it as its stock popup (``desk.js`` ``show_notes``) — :func:`refresh_desk_notes`
  makes that happen on the next page load instead of only after the next LOGIN;
* the PWA shows it as a sheet on open (``components/AnnouncementHost.vue``) via
  :func:`unseen` / :func:`mark_seen`;
* every phone with notifications on gets a push the moment it is published
  (:func:`push_on_publish`).

"Seen" is Frappe's own ``Note Seen By`` table, so dismissing it on either surface dismisses it
on both. A Note with "Notify On Every Login" is never marked seen — the PWA shows it once per
app launch, as the Desk does per login.

Field accounts are Website Users with no DocPerm on Note, so the reads here bypass
permissions — but only ever for public, active, notify-on-login Notes: exactly what the Desk
already shows every logged-in user.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime, strip_html

from container_depot.api import _require_authenticated_user

_ACTIVE = {"public": 1, "notify_on_login": 1}


def _active_notes():
	return frappe.get_all(
		"Note",
		filters={**_ACTIVE, "expire_notification_on": [">", now_datetime()]},
		fields=["name", "title", "content", "notify_on_every_login"],
		order_by="creation asc",
	)


@frappe.whitelist(methods=["GET"])
def unseen():
	"""GET — active announcements the caller has not dismissed yet, oldest first."""
	_require_authenticated_user()
	notes = _active_notes()
	if not notes:
		return []
	seen = set(
		frappe.get_all(
			"Note Seen By",
			filters={"parenttype": "Note", "parent": ["in", [n.name for n in notes]], "user": frappe.session.user},
			pluck="parent",
		)
	)
	return [n for n in notes if n.notify_on_every_login or n.name not in seen]


@frappe.whitelist(methods=["POST"])
def mark_seen(note: str):
	"""POST — dismiss one announcement for the caller (on the Desk too)."""
	_require_authenticated_user()
	row = frappe.db.get_value("Note", note, ["public", "notify_on_login", "notify_on_every_login"], as_dict=True)
	if not row or not (row.public and row.notify_on_login):
		frappe.throw(_("Pengumuman tidak ditemukan."), frappe.DoesNotExistError)
	if row.notify_on_every_login:
		return {"ok": True}
	user = frappe.session.user
	if not frappe.db.exists("Note Seen By", {"parenttype": "Note", "parent": note, "user": user}):
		# The child row alone, not Note.save(): a hundred handsets dismissing at once would
		# otherwise collide on the parent's `modified` (TimestampMismatchError).
		frappe.get_doc({
			"doctype": "Note Seen By", "parenttype": "Note", "parentfield": "seen_by",
			"parent": note, "user": user,
		}).db_insert()
	return {"ok": True}


def push_on_publish(doc, method=None):
	"""Note ``on_update``: push to every subscribed handset when an announcement goes live —
	newly public + notify-on-login, not on every later edit of its text."""
	if not (doc.public and doc.notify_on_login):
		return
	before = doc.get_doc_before_save()
	if before and before.public and before.notify_on_login:
		return
	if doc.expire_notification_on and str(doc.expire_notification_on) <= str(now_datetime()):
		return
	from container_depot.ess.push import SUBSCRIPTION_DOCTYPE, push_to_users

	users = frappe.get_all(SUBSCRIPTION_DOCTYPE, filters={"enabled": 1}, pluck="user", distinct=True)
	body = strip_html(doc.content or "").strip()
	push_to_users(users, title=doc.title, body=body[:180], url="/depot", tag=f"note-{doc.name}")


def refresh_desk_notes(bootinfo):
	"""``extend_bootinfo``: re-read the Desk's unseen Notes on every page load.

	Frappe only builds that list at LOGIN (``on_login`` → ``_get_unseen_notes``), and office
	accounts stay logged in for days — so an announcement would otherwise reach them a week
	late. One small query per Desk boot."""
	if frappe.session.user == "Guest":
		return
	from frappe.desk.doctype.note.note import _get_unseen_notes, get_unseen_notes

	_get_unseen_notes()  # rebuilds the per-user cache; returns nothing
	bootinfo.notes = get_unseen_notes()
