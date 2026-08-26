"""Re-lock the append-only ledgers now that Storage Charge has joined them.

``install.NO_MANUAL_CREATE`` is applied when a Custom DocPerm row is first written, and the
seeder is add-only — so a doctype added to the set after its rows already exist keeps the
create/delete flags it was seeded with. Storage Charge is exactly that case: it was created,
seeded, and only then classified as a derived ledger.

Same operation as ``v0_55.lock_gate_audit_doctypes``, reused rather than restated so the two
can never drift; that patch's docstring carries the reasoning.
"""

from container_depot.patches.v0_55.lock_gate_audit_doctypes import execute as _lock


def execute():
	_lock()
