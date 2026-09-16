"""Web Push subscriptions — the device half.

One person on two handsets is the normal case here (a phone in the yard, a tablet in the
office), and every bug this module guards against looks the same from the outside: one
device rings, the other stays silent, and nothing says which row is missing.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess import push

U = "push-two-devices@example.com"
EP1 = "https://fcm.googleapis.com/fcm/send/device-one-endpoint"
EP2 = "https://fcm.googleapis.com/fcm/send/device-two-endpoint"


def _sub(user, endpoint):
	doc = frappe.get_doc({
		"doctype": push.SUBSCRIPTION_DOCTYPE,
		"user": user,
		"endpoint": endpoint,
		"p256dh": "p256dh-" + endpoint[-6:],
		"auth": "auth-" + endpoint[-6:],
		"enabled": 1,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


class TestDepotPushSubscription(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", U):
			frappe.get_doc({
				"doctype": "User",
				"email": U,
				"first_name": "Push Two Devices",
				"send_welcome_email": 0,
				"user_type": "System User",
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		# The fixture user is this module's own, so it leaves with the module — a test
		# account left behind in the User list is noise for whoever runs the site next.
		frappe.set_user("Administrator")
		if frappe.db.exists("User", U):
			frappe.delete_doc("User", U, ignore_permissions=True, force=True, delete_permanently=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		self._wipe()
		self.name1 = _sub(U, EP1)
		self.name2 = _sub(U, EP2)

	def tearDown(self):
		frappe.set_user("Administrator")
		self._wipe()

	def _wipe(self):
		for name in frappe.get_all(push.SUBSCRIPTION_DOCTYPE, filters={"user": U}, pluck="name"):
			frappe.delete_doc(push.SUBSCRIPTION_DOCTYPE, name, ignore_permissions=True, force=True)

	def _mine(self):
		return set(frappe.get_all(push.SUBSCRIPTION_DOCTYPE, filters={"user": U}, pluck="name"))

	def test_unsubscribe_only_drops_the_endpoint_it_was_given(self):
		frappe.set_user(U)
		push.unsubscribe(EP2)
		self.assertEqual(self._mine(), {self.name1})

	def test_unsubscribe_without_an_endpoint_keeps_every_device(self):
		# The PWA sends an empty endpoint whenever the browser has no local subscription to
		# name. Treating that as "all of them" silenced the user's other phone.
		frappe.set_user(U)
		push.unsubscribe("")
		self.assertEqual(self._mine(), {self.name1, self.name2})

	def _rows_pushed(self, **kwargs):
		"""Names of the subscriptions ``deliver`` would post to, without any network.

		Both halves are stubbed: ``_keys`` because a test bench has no VAPID keypair and
		``deliver`` bails out at that check, and ``_send_one`` because the point here is
		which rows were selected, not what a push service does with them.
		"""
		sent_to = []
		keys, send_one = push._keys, push._send_one
		push._keys = lambda: ("pub", "priv")
		push._send_one = lambda row, payload, private: (sent_to.append(row.name), True)[1]
		try:
			push.deliver([U], title="t", **kwargs)
		finally:
			push._keys, push._send_one = keys, send_one
		return sent_to

	def test_deliver_with_an_endpoint_touches_that_device_only(self):
		self.assertEqual(self._rows_pushed(endpoint=EP2), [self.name2])

	def test_deliver_without_an_endpoint_reaches_both_devices(self):
		self.assertEqual(set(self._rows_pushed()), {self.name1, self.name2})
