"""No-op: yard placement rules were removed in the Phase 2 status/zone refactor.

This patch used to seed the ``Yard Placement Rule`` master (status -> allowed yard
categories). The depot no longer maps tanks to zones, so both the master and the
placement logic are gone. Kept as a no-op so already-applied instances and fresh
installs both migrate cleanly. The orphaned data/DocTypes are removed by
``v0_36.drop_yard_zones_and_placement_rules``.
"""

from __future__ import annotations


def execute():
	pass
