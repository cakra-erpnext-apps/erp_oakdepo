import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess import drafts

KEY = "position:ZZDRAFT0001"


class TestPwaDrafts(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("PWA Draft", {"draft_key": KEY})
		frappe.set_user("Administrator")

	def test_save_get_clear_round_trip(self):
		self.assertIsNone(drafts.draft_get(KEY))
		drafts.draft_save(KEY, {"location_note": "blok A", "photos": ["/files/x.jpg"]})
		drafts.draft_save(KEY, '{"location_note": "blok B"}')
		self.assertEqual(drafts.draft_get(KEY), {"location_note": "blok B"})
		drafts.draft_clear(KEY)
		self.assertIsNone(drafts.draft_get(KEY))

	def test_a_draft_belongs_to_its_user(self):
		drafts.draft_save(KEY, {"a": 1})
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			drafts.draft_get(KEY)
		frappe.set_user("test@example.com")
		self.assertIsNone(drafts.draft_get(KEY))

	def test_bad_key_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			drafts.draft_save("../etc", {})
