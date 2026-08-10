"""Make a retried PWA write safe to repeat.

The offline outbox (``frontend/src/data/outbox.js``) retries anything it could not confirm.
Being offline is the easy half of that: nothing reached the server, so nothing happened.
The dangerous half is LAG — the request arrives, the work is done, and the response is lost
on the way back. The handset cannot tell that apart from "never sent", so it sends again,
and without this the depot gets a second EIR, a second cleaning order, a second gate move.

So every queued write carries a ``request_id`` the client generated once. The first call
runs and its result is remembered; a repeat returns that same result without running
anything.

Scoped per user, so one operator's id can never replay into another's session.

Stored in the Frappe cache rather than a table. The window that matters is the retry window
— minutes to hours, not for ever — and a table would need its own cleanup job, permissions
and migration for something that is, in the end, a short-lived note to self. The cost of the
cache is honest and worth stating: after a restart or an eviction, a replay inside the window
can run twice. That is the same risk the system had before this existed, so the guard never
makes things worse, and it removes the failure in every ordinary case.
"""

from __future__ import annotations

import frappe

# Long enough to cover a shift's worth of retries, short enough that the cache is not being
# used as a database.
TTL_SECONDS = 24 * 60 * 60

_PREFIX = "oakdepo:req:"


def _key(request_id: str) -> str:
	return f"{_PREFIX}{frappe.session.user}:{request_id}"


def replayed(request_id: str | None):
	"""The stored result for ``request_id``, or ``None`` when this call is the first one.

	``None`` is also the answer when no id was supplied — a caller that opts out simply gets
	the old, unguarded behaviour. These endpoints all answer with a dict, so a genuine
	``None`` result is not a case that arises.

	``expires=True`` keeps this out of Frappe's per-request local cache, which does not know
	about the TTL and would happily serve an entry past its expiry.
	"""
	if not request_id:
		return None
	return frappe.cache().get_value(_key(request_id), expires=True)


def remember(request_id: str | None, result) -> None:
	"""Record what ``request_id`` produced, so a retry can be answered from here.

	Never raises. A result that will not pickle is simply not remembered: losing the guard
	for one call is a far better outcome than failing a write that already succeeded.
	"""
	if not request_id:
		return
	try:
		frappe.cache().set_value(_key(request_id), result, expires_in_sec=TTL_SECONDS)
	except Exception:
		frappe.log_error(title="idempotency: result not cacheable", message=frappe.get_traceback())


def guarded(request_id: str | None, fn):
	"""Run ``fn`` once per ``request_id``; answer later calls from the first result.

		return guarded(request_id, lambda: eir.save_draft(...))

	Deliberately not a decorator: the whitelisted endpoints take ``request_id`` as one
	keyword among twenty, and a decorator would have to guess which one it is. Being told
	explicitly at the call site is both clearer and harder to get wrong.
	"""
	previous = replayed(request_id)
	if previous is not None:
		return previous
	result = fn()
	remember(request_id, result)
	return result
