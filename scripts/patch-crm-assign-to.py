#!/usr/bin/env python3
from pathlib import Path

ROOT = Path("/home/frappe/frappe-bench/apps/crm")
OLD = "from frappe.desk.form.assign_to import _add as assign"
NEW = """try:
    from frappe.desk.form.assign_to import _add as assign
except ImportError:
    from frappe.desk.form.assign_to import add as assign"""

def main() -> int:
    if not ROOT.exists():
        print(f"crm app not found, skip: {ROOT}")
        return 0
    changed = 0
    for path in ROOT.rglob("*.py"):
        text = path.read_text()
        if OLD in text and "from frappe.desk.form.assign_to import add as assign" not in text:
            path.write_text(text.replace(OLD, NEW))
            print(f"patched {path}")
            changed += 1
    print(f"crm assign_to patch changed={changed}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
