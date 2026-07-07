"""Collapse the old ordered Container status enum onto the new presence-based set.

Booked / Available / Gate_Out keep their meaning; every mid-process status becomes
In_Depot (physically present, work pending); Cleaning_Completed / Released_Pending_
Pickup become Available (ready). Run as raw SQL so it bypasses the status guard and
the (now shorter) Select validation. inventory_stage is re-derived to match.
"""

import frappe

OLD_TO_NEW = {
    "Gate_In": "In_Depot",
    "Inspecting": "In_Depot",
    "Needs_Cleaning": "In_Depot",
    "Pending_Cleaning": "In_Depot",
    "Cleaning_In_Progress": "In_Depot",
    "Pending_Survey": "In_Depot",
    "Survey_In_Progress": "In_Depot",
    "Awaiting_MR_Approval": "In_Depot",
    "Repair_In_Progress": "In_Depot",
    "Awaiting_Recleaning_Approval": "In_Depot",
    "Recleaning_In_Progress": "In_Depot",
    "Cleaning_Completed": "Available",
    "Released_Pending_Pickup": "Available",
    # Booked / Available / Gate_Out unchanged.
}

STAGE = {"Booked": "Pre-Arrival", "In_Depot": "In Depot", "Available": "Ready", "Gate_Out": "Departed"}


def execute():
    for old, new in OLD_TO_NEW.items():
        frappe.db.sql(
            "UPDATE `tabContainer` SET status=%s WHERE status=%s", (new, old)
        )
    # Re-derive inventory_stage for every container to match the new status set.
    for status, stage in STAGE.items():
        frappe.db.sql(
            "UPDATE `tabContainer` SET inventory_stage=%s WHERE status=%s", (stage, status)
        )
    frappe.db.commit()
