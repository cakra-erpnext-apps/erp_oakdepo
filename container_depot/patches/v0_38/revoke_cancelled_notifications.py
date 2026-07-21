"""Clear the feed entries left behind by documents that were voided or deleted.

Cancelling never revoked its notifications before ``notify.revoke`` existed, so every
voided booking / bon was still sitting in the bell. This clears the backlog once; from
here the ``on_cancel`` doc_events keep it clean, and the daily
``tasks.sweep_stale_notifications`` catches what the ORM never sees (raw / bulk
deletes).

Same sweep as that daily job, so the rule lives in exactly one place.
"""

from container_depot.operations.notify import sweep_stale_notifications


def execute():
	removed = sweep_stale_notifications()
	if removed:
		print(f"revoked {removed} stale notification(s)")
