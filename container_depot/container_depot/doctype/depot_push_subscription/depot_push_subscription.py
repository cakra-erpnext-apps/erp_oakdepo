"""One row per browser that agreed to receive depot push notifications.

A subscription belongs to a (user, device) pair, not just a user: the same person on a
phone and a tablet holds two rows, and both should ring. The endpoint URL the browser
hands us is the identity, but it runs well past the 140 characters MariaDB will index, so
:attr:`endpoint_hash` carries the uniqueness constraint instead.
"""

import hashlib

import frappe
from frappe.model.document import Document


class DepotPushSubscription(Document):
	def validate(self):
		self.endpoint_hash = hash_endpoint(self.endpoint)


def hash_endpoint(endpoint: str) -> str:
	return hashlib.sha256((endpoint or "").encode()).hexdigest()
