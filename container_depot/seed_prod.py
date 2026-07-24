"""Container Depot — PRODUCTION master-data seeder (one file, one command).

    bench --site <site> execute container_depot.seed_prod.run     # seed everything
    bench --site <site> execute container_depot.seed_prod.clear   # remove the curated set

The blessed PRODUCTION entry point for the OAK master-data catalogue. It seeds
exactly the same datasets as the dev seeder (:mod:`container_depot.seed_dev`)
and *reuses its data definitions + idempotent helpers* — one source of truth, no
copy-paste of the 140-row item catalogue — but framed for production:
skip-if-exists, no dummy transactional data, clear summary output.

Seeded (in order)
-----------------
* Branch / Depot          — Oak Medan, Oak Surabaya · OAK1, OAK2, OAKSBY
* Cleaning Checklist,     — reuse the in-app master patches (already shipped data)
  Cargo, EIR Damage/Repair
  codes, EIR checklist
* UOM / Item Group / Item — full OAK service + M&R parts + packages catalogue
* Depot Service Menu      — Booking / Cleaning / Maintenance
* Customer                — principal masters (Stolt, Bertschi)

Most of the above also lands automatically on ``bench migrate`` (the seed
patches in patches.txt). This seeder additionally provisions the org-level
masters those patches don't: Branch, Depot, the Item catalogue, the Service
Menus, and the principal Customers.

Prices are intentionally NOT seeded — Item Price / tariff is commercial data;
load it per principal via the depot contract import (paste from Excel),
``container_depot.operations.doctype.depot_contract.depot_contract.import_tariff_lines``,
or the v0_11 price patches.

The dataset itself is defined once in :mod:`container_depot.seed_dev`; if you add
a dataset there, mirror the new loop here so production stays in sync.
"""

from __future__ import annotations

import frappe

from container_depot import seed_dev as _dev


def run():
    """Seed the full production master-data catalogue. Idempotent — safe to re-run."""
    print("=" * 64)
    print("Container Depot — PRODUCTION master-data seeder")
    print("=" * 64)

    for name in _dev.BRANCHES:
        _dev._ensure_branch(name)
    print(f"[seed_prod] Branch: {len(_dev.BRANCHES)}")

    for code, name, branch in _dev.DEPOTS:
        _dev._ensure_depot(code, name, branch)
    print(f"[seed_prod] Depot: {len(_dev.DEPOTS)}")

    # Shared masters that already ship inside the app's patches (idempotent).
    _dev._seed_cleaning_checklist()     # patches.v0_31
    _dev._seed_cargo()                  # patches.v0_12
    _dev._seed_eir_codes()              # patches.v0_6  — Inspection Damage + Repair Code
    _dev._seed_eir_checklist()          # patches.v0_39 — Inspection Checklist Item (138 rows)

    for uom in sorted({i[2] for i in _dev.ITEMS}):
        _dev._ensure_uom(uom)
    for name in _dev.ITEM_GROUPS:
        _dev._ensure_item_group(name)
    print(f"[seed_prod] Item Group: {len(_dev.ITEM_GROUPS)}")
    for _code, group, uom, name in _dev.ITEMS:
        _dev._ensure_item(group, uom, name)
    print(f"[seed_prod] Item: {len(_dev.ITEMS)}")

    for name, sequence, groups in _dev.MENUS:
        _dev._ensure_menu(name, sequence, groups)
    print(f"[seed_prod] Depot Service Menu: {len(_dev.MENUS)}")

    for name in _dev.CUSTOMERS:
        _dev._ensure_customer(name)
    print(f"[seed_prod] Customer: {len(_dev.CUSTOMERS)}")

    frappe.db.commit()
    print("=" * 64)
    print("[seed_prod] DONE — production master data seeded.")
    print("=" * 64)


def clear():
    """Reverse the curated set this seeder created.

    Delegates to the shared reversal in :func:`container_depot.seed_dev.clear`
    (the curated Branch/Depot/Item Group/Item/Service Menu/Customer set). The
    shared patch masters — Cargo, Cleaning Checklist, EIR codes/checklist — are
    standard masters and are left in place.
    """
    print("[seed_prod] clearing curated master data (delegating to seed_dev.clear) ...")
    _dev.clear()
