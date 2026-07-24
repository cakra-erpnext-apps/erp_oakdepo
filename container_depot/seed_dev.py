"""Container Depot — single-hit DEVELOPMENT seeder (one file, one command).

    bench --site <site> execute container_depot.seed_dev.run     # seed everything
    bench --site <site> execute container_depot.seed_dev.clear   # remove what this seeded

⚠️  DEVELOPMENT ONLY. Never run on production — it creates curated dummy master data
for a fresh dev site. Everything is idempotent (skip-if-exists), so re-running is safe.

What it seeds
-------------
* Branch                 — Oak Medan, Oak Surabaya
* Depot                  — OAK1, OAK2 (Medan) + OAKSBY (Surabaya)
* Cleaning Checklist     — reuses patches.v0_31 (12 rows)
* Cargo                  — reuses patches.v0_12 (data/cargo_list.json)
* EIR masters            — reuses patches.v0_6 (Inspection Damage + Repair Code) and
                           patches.v0_39 (Inspection Checklist Item, 138 rows)
* Item Group + Item      — from reference/seed/{Item_Group,Item}.csv (embedded below);
                           item_code == item_name (the descriptive name is the identity)
* Depot Service Menu     — Booking / Cleaning / Maintenance (group filters)
* Customer               — Stolt, Bertschi

Items are created as non-stock sales items (``is_stock_item=0``) so the seeder needs
no Company / warehouse / valuation — flip specific M&R parts to stock items later if
you want stock issue on repair completion.
"""

from __future__ import annotations

import frappe

# --- reuse existing in-app seeders (their data already ships inside the app) -------
from container_depot.patches.v0_12.seed_cargo import execute as _seed_cargo
from container_depot.patches.v0_31.seed_cleaning_checklist import execute as _seed_cleaning_checklist
from container_depot.patches.v0_6.seed_eir_codes import execute as _seed_eir_codes
from container_depot.patches.v0_39.seed_eir_checklist_positional import (
    execute as _seed_eir_checklist,
)

# ----------------------------------------------------------------------------------
# Curated dev data
# ----------------------------------------------------------------------------------
PARENT_ITEM_GROUP = "All Item Groups"

BRANCHES = ["Oak Medan", "Oak Surabaya"]

# (depot_code, depot_name, branch)
DEPOTS = [
    ("OAK1", "OAK 1", "Oak Medan"),
    ("OAK2", "OAK 2", "Oak Medan"),
    ("OAKSBY", "OAK SBY", "Oak Surabaya"),
]

# Depot Service Menu → the Item Groups it filters. (name, sequence, [item groups])
MENUS = [
    ("Booking", 1, ["LOLO"]),
    ("Cleaning", 2, ["Testing Charges", "Survey Fee", "Exterior Cleaning", "Interior Cleaning"]),
    ("Maintenance", 3, [
        "Manlid Seal",
        'Butterfly Valve (3.0")',
        'Footvalve (3.0")',
        'Spigot / Bottom Outlet (3.0")',
        'Airline Ball Valve (1.5")',
        "Safety Relief Valve",
        "Gasket (Bertschi)",
        "Cladding & Insulation",
        "Retainer Strap",
        "Thermometer & Gauge",
        "Document Holder",
        "Emergency Cable Assembly",
        "Swingbolt",
        "Frame & Metal Work",
        "Others (Bertschi)",
    ]),
]

CUSTOMERS = ["Stolt", "Bertschi"]

ITEM_GROUPS = [
    "LOLO",
    "Standard Depot Handling",
    "Testing Charges",
    "Survey Fee",
    "Exterior Cleaning",
    "Interior Cleaning",
    "Manlid Seal",
    'Butterfly Valve (3.0")',
    'Footvalve (3.0")',
    'Spigot / Bottom Outlet (3.0")',
    'Airline Ball Valve (1.5")',
    "Safety Relief Valve",
    "Gasket (Bertschi)",
    "Cladding & Insulation",
    "Retainer Strap",
    "Thermometer & Gauge",
    "Document Holder",
    "Emergency Cable Assembly",
    "Swingbolt",
    "Frame & Metal Work",
    "Others (Bertschi)",
    "Service Packages",
]

# (legacy_code, item_group, stock_uom, item_name). item_code == item_name now — the
# descriptive name is the item's identity; the first column is kept only as a
# reference to the original short SKU and is no longer used.
ITEMS = [
    ('L-OFF', 'LOLO', 'Nos', 'Lift Off'),
    ('L-ON', 'LOLO', 'Nos', 'Lift On'),
    ('SVC-EIR', 'Standard Depot Handling', 'Nos', 'EIR (Equipment Inspection Report)'),
    ('STORAGE-DAY', 'Standard Depot Handling', 'Day', 'Storage per day'),
    ('MANHOUR', 'Standard Depot Handling', 'Hour', 'Manhour Rate (labour)'),
    ('TEST-LEAK-1BAR', 'Testing Charges', 'Nos', '1 Bar Leak Test'),
    ('TEST-STEAM-TUBE', 'Testing Charges', 'Nos', 'Steam Tube Test'),
    ('TEST-2-5YR', 'Testing Charges', 'Nos', '2.5 Years Periodic Test'),
    ('TEST-5-0YR', 'Testing Charges', 'Nos', '5.0 Years Periodic Test'),
    ('SVY-CLEAN-CERT', 'Survey Fee', 'Nos', 'Cleaning Certificate from Class Surveyor'),
    ('SVY-CLASS-2-5YR', 'Survey Fee', 'Nos', 'Class Certification for Periodic Testing 2.5yr'),
    ('SVY-CLASS-5-0YR', 'Survey Fee', 'Nos', 'Class Certification for Periodic Testing 5yr'),
    ('SVY-CLEANLINESS', 'Survey Fee', 'Nos', 'Cleanliness Statement - In-House'),
    ('EXT-DETERGENT', 'Exterior Cleaning', 'Nos', 'Exterior Cleaning (Detergent)'),
    ('EXT-CHEMICAL', 'Exterior Cleaning', 'Nos', 'Exterior Cleaning (Chemical)'),
    ('EXT-HEAVY', 'Exterior Cleaning', 'Nos', 'Exterior Chemical Wash (Heavy Duty - Glue Stain)'),
    ('CLN-STANDARD', 'Interior Cleaning', 'Nos', 'Standard Clean'),
    ('CLN-DIFFICULT', 'Interior Cleaning', 'Nos', 'Difficult Clean'),
    ('CLN-FOODGRADE', 'Interior Cleaning', 'Nos', 'Foodgrade Clean'),
    ('CLN-LATEX', 'Interior Cleaning', 'Nos', 'Latex Clean'),
    ('CLN-BAFFLE', 'Interior Cleaning', 'Nos', 'Baffle Tank (add cleaning cost)'),
    ('CLN-RESIDUE', 'Interior Cleaning', 'Litre', 'Residue Disposal'),
    ('CLN-FLUSH', 'Interior Cleaning', 'Nos', 'Flushing'),
    ('CLN-RECLEAN', 'Interior Cleaning', 'Nos', 'Recleaning'),
    ('INT-METHANOL', 'Interior Cleaning', 'Nos', 'Methanol Wash / Rinse'),
    ('INT-PP-WASH', 'Interior Cleaning', 'Nos', 'P&P Wash'),
    ('INT-STEAM', 'Interior Cleaning', 'Hour', 'Steam Cleaning / Wash'),
    ('SEAL-MANLID-SWR', 'Manlid Seal', 'Nos', 'SWR Manlid Seal (Sweet White Rubber 10x14mm)'),
    ('SEAL-MANLID-SWR-10X20', 'Manlid Seal', 'Nos', 'SWR / Ring Type Manlid Seal (10x20mm / 12x14mm)'),
    ('SEAL-MANLID-PTFE-10X14', 'Manlid Seal', 'Nos', 'Braided PTFE Manlid Seal (10x14mm x 1.6m)'),
    ('SEAL-MANLID-PTFE-14X14', 'Manlid Seal', 'Nos', 'Braided PTFE Manlid Seal (14x14mm)'),
    ('SEAL-MANLID-SUPERTANKTYT', 'Manlid Seal', 'Nos', 'Supertanktyt Manlid Seal'),
    ('MR-BFV-TEFLON-SEAL', 'Butterfly Valve (3.0")', 'Nos', 'Renew 3.0" Butterfly Valve Main/Teflon Seal (Fort Vale)'),
    ('MR-BFV-NITRILE-ORING', 'Butterfly Valve (3.0")', 'Nos', 'Renew 3.0" Butterfly Valve Nitrile O-Ring'),
    ('MR-BFV-ENV-GASKET', 'Butterfly Valve (3.0")', 'Nos', 'Renew 3.0" Butterfly Valve Envelope Gasket'),
    ('MR-BFV-DISMANTLE', 'Butterfly Valve (3.0")', 'Nos', 'Butterfly Valve - Dismantle & Clean'),
    ('MR-FV-ENCAP-ORING', 'Footvalve (3.0")', 'Nos', 'Renew Highlift Footvalve Encapsulated O-Ring'),
    ('MR-FV-ENV-GASKET', 'Footvalve (3.0")', 'Nos', 'Renew Highlift Footvalve Envelope Gasket (4/8 holes)'),
    ('MR-FV-POLISH-LIGHT', 'Footvalve (3.0")', 'Nos', 'Footvalve Light Polish - Light Gouges & Scratches'),
    ('MR-FV-POLISH-MEDIUM', 'Footvalve (3.0")', 'Nos', 'Footvalve Medium Infill & Polish - Deep Gouges'),
    ('MR-FV-POLISH-CRITICAL', 'Footvalve (3.0")', 'Nos', 'Footvalve Critical Infill & Polish - Serration'),
    ('MR-FV-DISMANTLE', 'Footvalve (3.0")', 'Nos', 'Footvalve - Dismantle & Clean'),
    ('MR-FV-HANDLE', 'Footvalve (3.0")', 'Nos', 'Foot Valve Handle'),
    ('MR-VITON-ORING-FV', 'Footvalve (3.0")', 'Nos', 'Viton O-Ring - Footvalve Spindle'),
    ('MR-SPG-OUTLET-COMPAT', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'Renew 2.0" Spigot Outlet (Compatible)'),
    ('MR-SPG-OUTLET-FV', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'Renew 3.0" Spigot Outlet (Fort Vale)'),
    ('MR-SPG-ENV-GASKET', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'Renew 3.0" Spigot Outlet Envelope Gasket'),
    ('MR-SPG-BSP-CAP', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'Renew 3.0" BSP Cap S/S'),
    ('MR-SPG-BSP-CAP-SEAL', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'Renew 3.0" BSP Cap Seal'),
    ('MR-SPG-CHAIN', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'Renew Chain for BSP Cap'),
    ('MR-SPG-DISMANTLE', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'Spigot Outlet - Dismantle & Clean'),
    ('MR-TIR-TAB-SPG', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'TIR Tab Welding / Removal (Spigot)'),
    ('MR-BTS-DUSTCAP-3', 'Spigot / Bottom Outlet (3.0")', 'Nos', 'SS 3" Dust Cap'),
    ('MR-ABV-TEFLON-SEAL', 'Airline Ball Valve (1.5")', 'Nos', 'Renew 1.5" Ball Valve Teflon Seal Front+Rear (Fort Vale)'),
    ('MR-ABV-FRONT-SEAL', 'Airline Ball Valve (1.5")', 'Nos', '1.5" Airline Ball Front Teflon Seal (Fort Vale)'),
    ('MR-ABV-REAR-SEAL', 'Airline Ball Valve (1.5")', 'Nos', '1.5" Airline Ball Rear Teflon Seal (Fort Vale)'),
    ('MR-ABV-DUST-CAP', 'Airline Ball Valve (1.5")', 'Nos', 'Renew 1.5" Dust Cap S/S'),
    ('MR-BTS-DUSTCAP-1-5', 'Airline Ball Valve (1.5")', 'Nos', 'SS 1.5" Dust Cap'),
    ('MR-ABV-DUST-CAP-SEAL', 'Airline Ball Valve (1.5")', 'Nos', 'Renew 1.5" Dust Cap Seal'),
    ('MR-ABV-CHAIN', 'Airline Ball Valve (1.5")', 'Nos', 'Renew Chain for Dust Cap'),
    ('MR-TIR-TAB-ABV', 'Airline Ball Valve (1.5")', 'Nos', 'TIR Tab Welding / Removal (Airline)'),
    ('MR-ABV-DISMANTLE', 'Airline Ball Valve (1.5")', 'Nos', 'Airline Ball Valve - Dismantle & Clean'),
    ('MR-SRV-VAC-POPPET', 'Safety Relief Valve', 'Nos', 'Renew Relief Valve Vacuum Poppet'),
    ('MR-SRV-PRES-POPPET', 'Safety Relief Valve', 'Nos', 'Renew Relief Valve Pressure Poppet'),
    ('MR-SRV-PRES-SPRING', 'Safety Relief Valve', 'Nos', 'Renew 4.4bar Pressure Spring'),
    ('MR-SRV-VAC-SPRING', 'Safety Relief Valve', 'Nos', 'Renew 2.1Hg Vacuum Spring'),
    ('MR-SRV-CALIBRATE', 'Safety Relief Valve', 'Nos', 'Clean and Calibrate Relief Valve'),
    ('MR-SRV-PLATE-TEFLON', 'Safety Relief Valve', 'Nos', 'Renew Pressure Plate Combination Teflon Seal'),
    ('MR-SRV-PRES-OENCAP', 'Safety Relief Valve', 'Nos', 'Renew Pressure Plate Encapsulated O-Ring'),
    ('MR-SRV-VAC-OENCAP', 'Safety Relief Valve', 'Nos', 'Renew Vacuum Plate Encapsulated O-Ring'),
    ('MR-SRV-ENV-GASKET', 'Safety Relief Valve', 'Nos', 'Renew Relief Valve Envelope Gasket'),
    ('MR-SRV-ADAPTOR-GASKET', 'Safety Relief Valve', 'Nos', 'Renew Relief Valve Adaptor Flange Envelope Gasket'),
    ('MR-BTS-PV-OENCAP', 'Safety Relief Valve', 'Nos', 'PV Valve Encapsulated O-Ring'),
    ('MR-BTS-VAC-OENCAP', 'Safety Relief Valve', 'Nos', 'Vacuum Encapsulated O-Ring'),
    ('MR-GSK-PTFE', 'Gasket (Bertschi)', 'Nos', 'PTFE Gasket (generic - package inclusion)'),
    ('MR-GSK-FV-4H', 'Gasket (Bertschi)', 'Nos', 'Footvalve / Tank Envelope Gasket - 4 holes x 18mm x 178mm PCD'),
    ('MR-GSK-FV-8H', 'Gasket (Bertschi)', 'Nos', 'Footvalve / Tank Envelope Gasket - 8 holes x 14mm x 178mm PCD'),
    ('MR-GSK-BO-4H', 'Gasket (Bertschi)', 'Nos', 'Bottom Outlet Envelope Gasket (4 holes)'),
    ('MR-GSK-BO-NH', 'Gasket (Bertschi)', 'Nos', 'Bottom Outlet Envelope Gasket (w/o hole)'),
    ('MR-GSK-PV-ADAPTOR-6H', 'Gasket (Bertschi)', 'Nos', 'PV Valve Adaptor Flange Env. Gasket (6 holes)'),
    ('MR-GSK-AIRLINE-BFV-IN', 'Gasket (Bertschi)', 'Nos', '2" Flanged Airline BFV Inlet Env. Gasket - 4x18mm x 125mm PCD'),
    ('MR-GSK-AIRLINE-BV-OUT', 'Gasket (Bertschi)', 'Nos', '1.5" Flanged Airline Ball Valve Outlet PTFE Gasket - 4x18mm x 110mm PCD'),
    ('MR-GSK-PV-NH', 'Gasket (Bertschi)', 'Nos', 'PV Valve Envelope Gasket (w/o hole)'),
    ('MR-GSK-BFV-OUTLET', 'Gasket (Bertschi)', 'Nos', '3" Composite BFV Outlet Teflon Gasket (6 holes) - 6x11mm x 119mm PCD'),
    ('MR-GSK-DUSTCAP', 'Gasket (Bertschi)', 'Nos', '3" Dust Cap Teflon Gasket'),
    ('MR-GSK-SYPHON', 'Gasket (Bertschi)', 'Nos', 'Syphon Tube Envelope Gasket'),
    ('MR-GSK-PV-8H', 'Gasket (Bertschi)', 'Nos', 'PV Valve Flange Envelope Gasket (8 holes)'),
    ('MR-CLAD-PAINT-100', 'Cladding & Insulation', 'Nos', 'Cladding Painting 100% (estimate by %)'),
    ('MR-CLAD-PATCH-15X15', 'Cladding & Insulation', 'Nos', 'Cladding Patching 15cm x 15cm'),
    ('MR-CLAD-PATCH-15X30', 'Cladding & Insulation', 'Nos', 'Cladding Patching 15cm x 30cm'),
    ('MR-CLAD-PATCH-30X30', 'Cladding & Insulation', 'Nos', 'Cladding Patching 30cm x 30cm'),
    ('MR-CLAD-PATCH-30X60', 'Cladding & Insulation', 'Nos', 'Cladding Patching 30cm x 60cm'),
    ('MR-CLAD-PATCH-60X60', 'Cladding & Insulation', 'Nos', 'Cladding Patching 60cm x 60cm'),
    ('MR-CLAD-PATCH-60X90', 'Cladding & Insulation', 'Nos', 'Cladding Patching 60cm x 90cm'),
    ('MR-CLAD-PATCH-90X90', 'Cladding & Insulation', 'Nos', 'Cladding Patching 90cm x 90cm'),
    ('MR-CLAD-PATCH-90X120', 'Cladding & Insulation', 'Nos', 'Cladding Patching 90cm x 120cm'),
    ('MR-CLAD-PATCH-120X120', 'Cladding & Insulation', 'Nos', 'Cladding Patching 120cm x 120cm'),
    ('MR-CLAD-PATCH-120X240', 'Cladding & Insulation', 'Nos', 'Cladding Patching 120cm x 240cm'),
    ('MR-CLAD-RIVET', 'Cladding & Insulation', 'Nos', 'Rivet'),
    ('MR-INS-ROCKWOOL-15X15', 'Cladding & Insulation', 'Nos', 'Renew Rockwool Insulation 15cm x 15cm'),
    ('MR-INS-PU-15X15', 'Cladding & Insulation', 'Nos', 'Renew PU Insulation 15cm x 15cm'),
    ('MR-STRAP-SECTION-30', 'Retainer Strap', 'Nos', 'Section Retainer Strap 30cm'),
    ('MR-STRAP-SECTION-ADD30', 'Retainer Strap', 'Nos', 'Section Retainer Strap Additional 30cm (thereafter)'),
    ('MR-STRAP-STRAIGHTEN-30', 'Retainer Strap', 'Nos', 'Straighten and Rivet 30cm'),
    ('MR-THERMO-ANALOG', 'Thermometer & Gauge', 'Nos', 'Renew Analog Thermometer (-20 to 140C)'),
    ('MR-THERMO-DIGITAL', 'Thermometer & Gauge', 'Nos', 'Renew Digital Thermometer (0 to 150C)'),
    ('MR-BTS-THERMO-ANALOG', 'Thermometer & Gauge', 'Nos', 'Thermometer Analog (0-150C) w/ oil filled'),
    ('MR-PGAUGE-0-7BAR', 'Thermometer & Gauge', 'Nos', 'Renew Pressure Gauge 0-7 bar S/S, 2.5" Dial Silicon'),
    ('MR-BTS-PGAUGE', 'Thermometer & Gauge', 'Nos', 'Pressure Gauge (0-10bar) w/ oil filled'),
    ('MR-DOCHOLDER-3', 'Document Holder', 'Nos', 'Document Holder (Compact) 3"'),
    ('MR-DOCHOLDER-4', 'Document Holder', 'Nos', 'Document Holder (Compact) 4"'),
    ('MR-ECABLE-ASSY', 'Emergency Cable Assembly', 'Nos', 'Renew Emergency Cable Assembly'),
    ('MR-ECABLE-TRIP-BRACKET', 'Emergency Cable Assembly', 'Nos', 'Renew Trip Bracket (incl. tighten cable)'),
    ('MR-ECABLE-CABLE', 'Emergency Cable Assembly', 'Nos', 'Renew Cable'),
    ('MR-ECABLE-TIGHTEN', 'Emergency Cable Assembly', 'Nos', 'Tighten Emergency Cable (incl. 2x wire clip)'),
    ('MR-SWINGBOLT-STD', 'Swingbolt', 'Nos', 'Renew Swingbolt - Standard Type'),
    ('MR-SWINGBOLT-BSW', 'Swingbolt', 'Nos', 'Renew Swingbolt - 0.75" BSW, 90mm, 16mm Eye'),
    ('MR-BTS-SWINGBOLT', 'Swingbolt', 'Nos', 'Swing Bolt FV (16" or 19")'),
    ('MR-FRM-CORNER-POST', 'Frame & Metal Work', 'Nos', 'Renew Corner Post'),
    ('MR-FRM-CORNER-POST-INS30', 'Frame & Metal Work', 'Nos', 'Insert Corner Post 30cm'),
    ('MR-FRM-CORNER-POST-INS15', 'Frame & Metal Work', 'Nos', 'Insert Corner Post Additional 15cm (thereafter 30cm)'),
    ('MR-FRM-CORNER-CASTING', 'Frame & Metal Work', 'Nos', 'Renew / Replace Corner Casting'),
    ('MR-FRM-TOP-RAIL', 'Frame & Metal Work', 'Nos', 'Renew Top Side Rail'),
    ('MR-FRM-TOP-RAIL-INS15', 'Frame & Metal Work', 'Nos', 'Insert Top Side Rail 15cm'),
    ('MR-FRM-TOP-RAIL-INS30', 'Frame & Metal Work', 'Nos', 'Insert Top Side Rail 30cm'),
    ('MR-FRM-TOP-RAIL-SEC15', 'Frame & Metal Work', 'Nos', 'Section Top Side Rail 15cm'),
    ('MR-FRM-TOP-RAIL-SEC30', 'Frame & Metal Work', 'Nos', 'Section Top Side Rail 30cm'),
    ('MR-FRM-END-RAIL', 'Frame & Metal Work', 'Nos', 'Renew End Rail 4"x2" (Standard)'),
    ('MR-FRM-END-RAIL-INS15', 'Frame & Metal Work', 'Nos', 'Insert End Rail / Bracing 15cm'),
    ('MR-FRM-END-RAIL-INS30', 'Frame & Metal Work', 'Nos', 'Insert End Rail / Bracing 30cm'),
    ('MR-FRM-END-RAIL-SEC15', 'Frame & Metal Work', 'Nos', 'Section End Rail / Bracing 15cm'),
    ('MR-FRM-END-RAIL-SEC30', 'Frame & Metal Work', 'Nos', 'Section End Rail / Bracing 30cm'),
    ('MR-FRM-GUSSET', 'Frame & Metal Work', 'Nos', 'Renew / Replace Gusset Plate'),
    ('MR-FRM-GUSSET-STRAIGHTEN', 'Frame & Metal Work', 'Nos', 'Straighten and Weld Gusset Plate'),
    ('MR-FRM-BOTTOM-RAIL', 'Frame & Metal Work', 'Nos', 'Renew Bottom Side Rail 4"x4" (Standard)'),
    ('MR-FRM-VBP-100', 'Frame & Metal Work', 'Nos', 'V/BP 100%'),
    ('MR-BTS-FRAME-TRAP', 'Frame & Metal Work', 'Nos', 'Frame Trap'),
    ('MR-BTS-STEAMCAP-SS', 'Others (Bertschi)', 'Nos', 'SS Steam Cap 3/4" or 1"'),
    ('MR-BTS-STEAMCAP-PVC', 'Others (Bertschi)', 'Nos', 'PVC Steam Cap 3/4" or 1"'),
    ('PKG-STOLT-EMPTYCLEAN', 'Service Packages', 'Nos', 'Empty Cleaned Tank Package (Stolt)'),
    ('PKG-BTS-EMPTYCLEAN', 'Service Packages', 'Nos', 'Empty Clean Tank Package (Bertschi)'),
    ('PKG-BTS-LIGHTCLEAN', 'Service Packages', 'Nos', 'Light Cleaning Package (Bertschi)'),
    ('PKG-BTS-MEDIUMCLEAN', 'Service Packages', 'Nos', 'Medium Cleaning Package (Bertschi)'),
    ('PKG-BTS-HARDCLEAN', 'Service Packages', 'Nos', 'Hard Cleaning Package (Bertschi)'),
    ('PKG-BTS-EIR-STORAGE', 'Service Packages', 'Nos', 'EIR & Storage Package (Bertschi, Empty Clean Tank only)'),
]


# ----------------------------------------------------------------------------------
# Helpers (idempotent)
# ----------------------------------------------------------------------------------
def _ensure_uom(uom):
    if uom and not frappe.db.exists("UOM", uom):
        frappe.get_doc({"doctype": "UOM", "uom_name": uom, "enabled": 1}).insert(ignore_permissions=True)


def _ensure_branch(name):
    if not frappe.db.exists("Branch", name):
        frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True)


def _ensure_depot(code, name, branch):
    if not frappe.db.exists("Depot", code):
        frappe.get_doc({
            "doctype": "Depot", "depot_code": code, "depot_name": name,
            "branch": branch, "is_active": 1,
        }).insert(ignore_permissions=True)


def _ensure_item_group(name):
    if not frappe.db.exists("Item Group", name):
        frappe.get_doc({
            "doctype": "Item Group", "item_group_name": name,
            "parent_item_group": PARENT_ITEM_GROUP, "is_group": 0,
        }).insert(ignore_permissions=True)


def _ensure_item(group, uom, name):
    """item_code == item_name — the descriptive name is the item's identity."""
    if frappe.db.exists("Item", name):
        return
    frappe.get_doc({
        "doctype": "Item", "item_code": name, "item_name": name,
        "item_group": group, "stock_uom": uom,
        "is_stock_item": 0, "is_sales_item": 1,
    }).insert(ignore_permissions=True)


def _ensure_menu(name, sequence, groups):
    if frappe.db.exists("Depot Service Menu", name):
        return
    doc = frappe.get_doc({
        "doctype": "Depot Service Menu", "menu_name": name,
        "is_active": 1, "sequence": sequence,
    })
    for g in groups:
        doc.append("item_groups", {"item_group": g})
    doc.insert(ignore_permissions=True)


def _default_customer_group():
    for preferred in ("Commercial", "All Customer Groups"):
        if frappe.db.exists("Customer Group", preferred):
            return preferred
    return frappe.db.get_value("Customer Group", {"is_group": 0}, "name")


def _default_territory():
    if frappe.db.exists("Territory", "All Territories"):
        return "All Territories"
    return frappe.db.get_value("Territory", {}, "name")


def _ensure_customer(name):
    if frappe.db.exists("Customer", name):
        return
    frappe.get_doc({
        "doctype": "Customer", "customer_name": name,
        "customer_group": _default_customer_group(),
        "territory": _default_territory(),
    }).insert(ignore_permissions=True)


# ----------------------------------------------------------------------------------
# Entry points
# ----------------------------------------------------------------------------------
def run():
    """Seed the full dev dataset in one hit. Idempotent."""
    print("=" * 64)
    print("Container Depot DEV seeder — DEVELOPMENT ONLY")
    print("=" * 64)

    for name in BRANCHES:
        _ensure_branch(name)
    print(f"[seed_dev] Branch: {len(BRANCHES)}")

    for code, name, branch in DEPOTS:
        _ensure_depot(code, name, branch)
    print(f"[seed_dev] Depot: {len(DEPOTS)}")

    _seed_cleaning_checklist()     # patches.v0_31
    _seed_cargo()                  # patches.v0_12
    _seed_eir_codes()              # patches.v0_6  — Inspection Damage + Repair Code (EIR masters)
    _seed_eir_checklist()          # patches.v0_39 — Inspection Checklist Item (8 areas, 138 rows)

    for uom in sorted({i[2] for i in ITEMS}):
        _ensure_uom(uom)
    for name in ITEM_GROUPS:
        _ensure_item_group(name)
    print(f"[seed_dev] Item Group: {len(ITEM_GROUPS)}")
    for _code, group, uom, name in ITEMS:
        _ensure_item(group, uom, name)
    print(f"[seed_dev] Item: {len(ITEMS)}")

    for name, sequence, groups in MENUS:
        _ensure_menu(name, sequence, groups)
    print(f"[seed_dev] Depot Service Menu: {len(MENUS)}")

    for name in CUSTOMERS:
        _ensure_customer(name)
    print(f"[seed_dev] Customer: {len(CUSTOMERS)}")

    frappe.db.commit()
    print("=" * 64)
    print("[seed_dev] DONE — all dev master data seeded.")
    print("=" * 64)


def clear():
    """Best-effort removal of the data this seeder created (curated set only).

    Leaves the shared masters from the reused patches (Cargo, Cleaning Checklist,
    EIR Damage/Repair Codes, Inspection Checklist) in place — those are standard
    masters, not dev-only.
    """
    print("[seed_dev] clearing dev-seeded curated data ...")

    def _del(dt, name):
        try:
            if frappe.db.exists(dt, name):
                frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
        except Exception as exc:  # noqa: BLE001 — best-effort dev cleanup
            print(f"  skip {dt} {name}: {exc}")

    for name, _seq, _groups in MENUS:
        _del("Depot Service Menu", name)
    for _code, _group, _uom, name in ITEMS:
        _del("Item", name)
    for name in ITEM_GROUPS:
        _del("Item Group", name)
    for code, _name, _branch in DEPOTS:
        _del("Depot", code)
    for name in BRANCHES:
        _del("Branch", name)
    for name in CUSTOMERS:
        _del("Customer", name)

    frappe.db.commit()
    print("[seed_dev] clear DONE.")
