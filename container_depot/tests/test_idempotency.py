"""A retried PWA write must not do the work twice.

The offline outbox replays anything it could not confirm. Being offline is the harmless
case — nothing reached the server. The case these tests are about is LAG: the request
arrives, the work happens, and the response is lost coming back. The handset cannot tell
that apart from "never sent", so it sends again.

Without the guard that produces a second EIR, a second cleaning order, a second gate move.
"""

from __future__ import annotations

import importlib
import inspect
from unittest.mock import patch

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


# Every PWA write the offline outbox can replay, with the implementation each one delegates
# to. Add a row here when a new queued endpoint appears — the tests below hold the whole list
# to the same two rules, so a new endpoint that forgets the guard fails immediately rather
# than waiting for a duplicate to show up in the depot.
#
# Format: (ess module path, endpoint name, implementation module path, implementation name).
REPLAYED_ENDPOINTS = [
	("container_depot.ess.inspections", "eir_start", "container_depot.container_depot.eir", "start_eir"),
	("container_depot.ess.inspections", "eir_save_draft", "container_depot.container_depot.eir", "save_draft"),
	("container_depot.ess.inspections", "eir_create", "container_depot.container_depot.eir", "create_eir"),
	("container_depot.ess.inspections", "eir_withdraw_review", "container_depot.container_depot.eir", "withdraw_review"),
	("container_depot.ess.inspections", "eir_request_revision", "container_depot.container_depot.eir", "request_revision"),
	("container_depot.ess.inspections", "eir_assign_photo_section", "container_depot.container_depot.eir", "assign_photo_section"),
	("container_depot.ess.cleaning", "cleaning_start", "container_depot.container_depot.cleaning", "start_cleaning"),
	("container_depot.ess.cleaning", "cleaning_order_save", "container_depot.container_depot.cleaning", "save_cleaning_order"),
	("container_depot.ess.repairs", "mr_start", "container_depot.container_depot.mr", "start_repair"),
	("container_depot.ess.repairs", "mr_order_save", "container_depot.container_depot.mr", "save_mr_order"),
	(
		# Letak tank INSERTS a reading rather than updating one, so a replay on a bad signal
		# would leave two identical readings minutes apart and make the tank look re-checked.
		"container_depot.ess.container_position", "position_record",
		"container_depot.container_depot.container_position", "record_position",
	),
	(
		"container_depot.ess.tank_survey", "survey_lowered",
		"container_depot.container_depot.tank_survey", "mark_lowered",
	),
	(
		"container_depot.ess.tank_survey", "survey_finish",
		"container_depot.container_depot.tank_survey", "finish_survey",
	),
]


class TestEndpointIdempotency(FrappeTestCase):
	"""The guard where it actually matters: every endpoint the outbox replays."""

	def setUp(self):
		super().setUp()
		# Administrator clears require_menu on every menu, so these tests exercise the guard
		# rather than the permission layer (which has its own tests).
		frappe.set_user("Administrator")

	def _endpoint(self, module_path, name):
		return getattr(importlib.import_module(module_path), name)

	def test_every_replayed_endpoint_takes_an_optional_request_id(self):
		for module_path, name, _impl_mod, _impl in REPLAYED_ENDPOINTS:
			with self.subTest(endpoint=name):
				params = inspect.signature(self._endpoint(module_path, name)).parameters
				self.assertIn(
					"request_id", params,
					f"{name} is replayed by the offline outbox and must be guarded",
				)
				self.assertIsNone(
					params["request_id"].default,
					"the guard must be opt-in, never required — Desk and automation callers pass no id",
				)

	def test_every_replayed_endpoint_actually_runs_the_work_once(self):
		"""Accepting a ``request_id`` is not the same as honouring it.

		The mistake this catches is the easy one: adding the keyword to the signature and
		forgetting to wrap the call in ``guarded``. The endpoint would look correct, pass the
		signature test above, and still raise a second EIR in the yard.

		The implementation is replaced with a counter, so this needs no fixtures and asserts
		the only thing that matters — the work behind the endpoint ran exactly once.
		"""
		for module_path, name, impl_module_path, impl_name in REPLAYED_ENDPOINTS:
			with self.subTest(endpoint=name):
				endpoint = self._endpoint(module_path, name)
				impl_module = importlib.import_module(impl_module_path)
				request_id = frappe.generate_hash(length=12)
				calls = []

				def _fake(*args, **kwargs):
					calls.append(1)
					return {"ok": True, "n": len(calls)}

				with patch.object(impl_module, impl_name, _fake):
					first = endpoint(request_id=request_id)
					second = endpoint(request_id=request_id)

				self.assertEqual(len(calls), 1, f"{name} ran its work twice for one request_id")
				self.assertEqual(first, second, f"{name} did not answer the replay with the first result")

	def test_without_a_request_id_the_work_runs_every_time(self):
		"""The guard must never become an accidental cache for ordinary un-queued callers."""
		endpoint = self._endpoint("container_depot.ess.cleaning", "cleaning_start")
		impl_module = importlib.import_module("container_depot.container_depot.cleaning")
		calls = []

		with patch.object(impl_module, "start_cleaning", lambda *a, **k: calls.append(1)):
			endpoint(cleaning_order="CO-0001")
			endpoint(cleaning_order="CO-0001")

		self.assertEqual(len(calls), 2)


class TestGateGenerateOrderIdempotency(FrappeTestCase):
	"""The gate bon is guarded inline rather than through ``guarded`` — same contract.

	It is the one write the PWA cannot queue (issuing a bon needs a live read of the booking's
	payment and block status), which makes lag the *only* protection it needs and the only one
	it has.
	"""

	def test_a_replay_answers_from_the_first_result_without_touching_the_booking(self):
		from container_depot.api import gate_generate_order

		frappe.set_user("Administrator")
		request_id = frappe.generate_hash(length=12)
		remember(request_id, {"success": True, "order_name": "ORD-TEST-0001"})

		# A booking that does not exist: reaching the work at all would throw. Getting the
		# stored answer back proves the guard sits in FRONT of the work, not after it.
		result = gate_generate_order(
			booking="OAK-DOES-NOT-EXIST", selected_codes="[]", request_id=request_id
		)
		self.assertEqual(result["order_name"], "ORD-TEST-0001")
