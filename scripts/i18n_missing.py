#!/usr/bin/env python3
"""List server messages the depot PWA's language packs do not cover yet.

The PWA speaks Indonesian or English (container_depot/depot_lang.py). App messages are
written in either language, so each `_("…")` literal must appear as a source in exactly
one pack: container_depot/translations/id.csv (English source -> Indonesian) or
en-GB.csv (Indonesian source -> English). This prints every literal in neither, one per
line, for a human (or Claude) to translate into the right file.

    python3 scripts/i18n_missing.py            # missing sources
    python3 scripts/i18n_missing.py --all      # every source literal

Master data (EIR checklist, damage / repair codes, …) is not in the code; it is listed by
`bench --site <site> execute container_depot.container_depot.i18n_master.master_strings`.
"""

import ast
import csv
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "container_depot"
PACKS = [APP / "translations" / "id.csv", APP / "translations" / "en-GB.csv"]


def literals():
	found = set()
	for path in APP.rglob("*.py"):
		if "tests" in path.parts or path.name.startswith("test_"):
			continue
		for node in ast.walk(ast.parse(path.read_text(), str(path))):
			if not (isinstance(node, ast.Call) and node.args):
				continue
			fn = node.func
			name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
			arg = node.args[0]
			if name in ("_", "_lt") and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
				found.add(arg.value.strip())
	return found


def covered():
	done = set()
	for pack in PACKS:
		if pack.exists():
			with pack.open(newline="") as f:
				done.update(row[0].replace("\\n", "\n").strip() for row in csv.reader(f) if row)
	return done


if __name__ == "__main__":
	todo = literals() if "--all" in sys.argv else literals() - covered()
	for s in sorted(todo):
		print(s.replace("\n", "\\n"))
