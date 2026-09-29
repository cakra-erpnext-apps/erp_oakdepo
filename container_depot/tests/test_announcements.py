"""Manual announcements: a public, notify-on-login Note reaches the PWA until dismissed."""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess import announcements


class TestAnnouncements(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.notes = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for n in self.notes:
			frappe.db.delete("Note Seen By", {"parent": n})
			frappe.db.delete("Note", n)
		frappe.db.commit()

	def _note(self, title, **kw):
		doc = frappe.get_doc({"doctype": "Note", "title": title, "public": 1, "notify_on_login": 1, **kw}).insert()
		self.notes.append(doc.name)
		return doc.name

	def _unseen(self):
		return {n.name for n in announcements.unseen()}

	def test_shown_until_dismissed_and_private_notes_never(self):
		live = self._note("ZZTEST live")
		private = self._note("ZZTEST private", public=0)
		self.assertIn(live, self._unseen())
		self.assertNotIn(private, self._unseen())
		announcements.mark_seen(live)
		self.assertNotIn(live, self._unseen())

	def test_every_login_note_is_never_marked_seen(self):
		every = self._note("ZZTEST every", notify_on_every_login=1)
		announcements.mark_seen(every)
		self.assertIn(every, self._unseen())
