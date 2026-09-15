"""Stop pulling mail into the site. No incoming email, no scheduled pull.

An Email Account per operator does not fit the queue this site runs. Frappe's scheduler
pulls every enabled incoming account every 10 minutes (``frappe/hooks.py``), and each pull
fetches up to 100 full message bodies per folder, one IMAP FETCH at a time
(``EmailServer.get_messages``). ``queue-short`` is a single RQ worker shared with
``default``, and its jobs are killed at 300s. At ~50 accounts one cycle cannot finish
inside its own 10 minutes: the queue never drains, pulls die half-done, and every other
short job — push notifications, outgoing mail, gate work — waits behind them.

So the intake is switched off at both taps, because either one alone still lets mail in:

1. the scheduled job — ``sync_jobs`` only ever rewrites a job's frequency, so ``stopped``
   survives every later ``bench migrate``;
2. ``enable_incoming`` on the accounts themselves, which is also what the manual "Pull
   Emails" button on the Email Account form goes through.

Reversible by hand: untick Stopped on the Scheduled Job Type, tick Enable Incoming back on
the accounts that should have it (a handful of shared mailboxes, not one per operator).
Outgoing mail is untouched — this only turns off receiving.
"""

import frappe

PULL_JOB = "frappe.email.doctype.email_account.email_account.pull"


def execute():
	if job := frappe.db.exists("Scheduled Job Type", {"method": PULL_JOB}):
		frappe.db.set_value("Scheduled Job Type", job, "stopped", 1)

	accounts = frappe.get_all("Email Account", filters={"enable_incoming": 1}, pluck="name")
	for account in accounts:
		# db_set, not save: the doctype's validate dials the mail server, and a patch has no
		# business waiting on IMAP just to clear a checkbox.
		frappe.db.set_value("Email Account", account, "enable_incoming", 0)

	if accounts:
		print(f"stop_email_intake: incoming turned off on {len(accounts)} Email Account(s)")
