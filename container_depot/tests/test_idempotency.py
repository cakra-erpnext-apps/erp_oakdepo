"""A retried PWA write must not do the work twice.

The offline outbox replays anything it could not confirm. Being offline is the harmless
case — nothing reached the server. The case these tests are about is LAG: the request
arrives, the work happens, and the response is lost coming back. The handset cannot tell
that apart from "never sent", so it sends again.

Without the guard that produces a second EIR, a second cleaning order, a second gate move.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess.idempotency import guarded, remember, replayed


class TestIdempotency(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.calls = 0

	def _work(self):
		self.calls += 1
		return {"ran": self.calls}

	def test_a_replay_returns_the_first_result_without_running_again(self):
		request_id = frappe.generate_hash(length=12)
		first = guarded(request_id, self._work)
		second = guarded(request_id, self._work)

		self.assertEqual(self.calls, 1, "the work must run exactly once")
		self.assertEqual(first, second, "the replay answers with what the first call produced")

	def test_a_different_id_is_a_different_request(self):
		guarded(frappe.generate_hash(length=12), self._work)
		guarded(frappe.generate_hash(length=12), self._work)
		self.assertEqual(self.calls, 2, "two genuine submissions are two pieces of work")

	def test_no_id_means_no_guard(self):
		"""Callers that opt out keep the old behaviour rather than getting a surprise."""
		guarded(None, self._work)
		guarded(None, self._work)
		self.assertEqual(self.calls, 2)

	def test_ids_never_cross_between_users(self):
		"""Two handsets can mint the same id; one operator must never read the other's result."""
		request_id = "shared-by-accident"
		users = ("idem-a@example.com", "idem-b@example.com")
		for email in users:
			if not frappe.db.exists("User", email):
				frappe.get_doc({
					"doctype": "User",
					"email": email,
					"first_name": email.split("@")[0],
					"send_welcome_email": 0,
				}).insert(ignore_permissions=True)
		try:
			frappe.set_user(users[0])
			guarded(request_id, self._work)
			frappe.set_user(users[1])
			guarded(request_id, self._work)
			self.assertEqual(self.calls, 2, "the second user's call is its own request")
		finally:
			frappe.set_user("Administrator")
			for email in users:
				if frappe.db.exists("User", email):
					frappe.delete_doc("User", email, ignore_permissions=True, force=True)
			frappe.db.commit()

	def test_an_unstorable_result_still_returns(self):
		"""The guard is an optimisation on top of the write, never a gate in front of it.

		A result that will not pickle must cost us the cross-request dedup — never the call
		itself, which by then has already changed the database. (Frappe still keeps it in the
		per-request local cache, so the value survives inside this request; what is lost is
		the Redis copy a later retry would have read.)
		"""
		request_id = frappe.generate_hash(length=12)
		unstorable = {"fn": lambda: None}  # a lambda cannot be pickled
		self.assertEqual(guarded(request_id, lambda: unstorable), unstorable)

	def test_remember_and_replay_round_trip(self):
		request_id = frappe.generate_hash(length=12)
		self.assertIsNone(replayed(request_id), "an unseen id has no stored answer")
		remember(request_id, {"inspection": "EIR-TEST-0001", "pending_review": True})
		self.assertEqual(replayed(request_id)["inspection"], "EIR-TEST-0001")


class TestEirEndpointIdempotency(FrappeTestCase):
	"""The guard where it actually matters: the endpoint the outbox replays."""

	def test_eir_save_draft_accepts_and_honours_a_request_id(self):
		import inspect

		from container_depot.ess import inspections

		for endpoint in (inspections.eir_save_draft, inspections.eir_create):
			with self.subTest(endpoint=endpoint.__name__):
				params = inspect.signature(endpoint).parameters
				self.assertIn(
					"request_id",
					params,
					f"{endpoint.__name__} is replayed by the offline outbox and must be guarded",
				)
				self.assertIsNone(params["request_id"].default, "the guard must be opt-in, never required")
