"""Pin the finance master switch for tests that need invoicing.

A site may legitimately run with finance off (operations-only — see
``container_depot.finance``), and on such a site no Sales Invoice is raised at all. Any test
that asserts something about invoicing has to say so rather than inherit it from whatever
this particular site happens to be configured as; otherwise the suite passes or fails
depending on a setting that has nothing to do with the code under test.

Call :func:`require_finance` from ``setUp``. It restores the site's own setting afterwards,
so running the suite never changes how the depot is configured.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from container_depot import finance


def require_finance(case, enabled: bool = True):
	"""Force the switch for the duration of one test (or class), then put it back.

	Pass the ``self`` of a ``setUp`` or the ``cls`` of a ``setUpClass`` — the cleanup is
	registered at whichever scope it was asked for.

	Committed, not just written: these tests submit documents, and anything that commits
	mid-test would otherwise pin whatever the switch happened to be at that moment.
	"""
	before = frappe.db.get_single_value(finance.SETTINGS, "enable_finance", cache=False)
	want = 1 if enabled else 0
	if cint(before) == want:
		# Already how the test wants it: nothing to change, nothing to restore — and, more
		# importantly, nothing to COMMIT. FrappeTestCase rolls the DB back once per CLASS,
		# not per test (`addClassCleanup(_rollback_db)`), so a commit in setUp makes every
		# row the previous tests wrote permanent. That is how TestGate was leaving six
		# Container Bookings behind on every suite run.
		finance.clear_cache()
		return

	frappe.db.set_single_value(finance.SETTINGS, "enable_finance", want)
	frappe.db.commit()
	finance.clear_cache()

	def restore():
		frappe.db.set_single_value(finance.SETTINGS, "enable_finance", cint(before))
		frappe.db.commit()
		finance.clear_cache()

	if isinstance(case, type):
		case.addClassCleanup(restore)
	else:
		case.addCleanup(restore)
