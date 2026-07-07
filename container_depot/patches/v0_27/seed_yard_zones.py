"""No-op: yard zones were removed in the Phase 2 status/zone refactor.

This patch used to seed the ``Yard Zone`` master + SOP zones. The depot no longer
maps tanks to zones (presence-based status only), so the ``Yard Zone`` DocType is
gone. Kept as a no-op so already-applied instances and fresh installs both migrate
cleanly. The orphaned data/DocTypes are removed by
``v0_36.drop_yard_zones_and_placement_rules``.
"""

from __future__ import annotations


def execute():
	pass
