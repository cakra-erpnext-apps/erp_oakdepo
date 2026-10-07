"""The day a tank came into the depot and the day it left (user, 2026-10-07).

The bons decide both: **Tanggal Bongkar** is the day the tank entered, **Tanggal Muat** the
day it left ("Tanggal Bongkar/Muat itu sudah menganggap container itu masuk dan keluar depo
pada tanggal itu"). They are the operator's dates, never the moment somebody pressed Submit,
and an EIR never moves them: the EIR's own date lives on the EIR ("beda tempat, cukup update
di tempat sendiri").

Written to two places:

* the visit's **Gate Entry** (``in_date`` / ``out_date``) — one row per visit, which is what
  storage counts and bills from (:mod:`container_depot.storage`);
* the **Container** master (``in_date`` / ``out_date``) — the latest visit only, for the
  inventory, the tank's age in the depot and "has it arrived yet".

The Gate Entry's ``gate_in_timestamp`` / ``gate_out_timestamp`` stay what they always were:
when the system registered the event. Nothing that counts days reads them any more.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, today


def bon_day(order) -> "datetime.date":
	"""The bon's own date: Tanggal Bongkar or Tanggal Muat (today for a bon without one)."""
	return getdate(order.get("tanggal_bongkar") or order.get("tanggal_muat") or today())


def _rows(order):
	return order.get("containers") or []


def follow_bongkar(order) -> None:
	"""A submitted Order Bongkar's Tanggal Bongkar was corrected: move the arrival with it.

	Every Gate Entry this bon opened takes the new day, and so does the master of each tank
	whose latest arrival is still this bon (one that has come in again since keeps its newer
	date). The storage ledger is re-derived for each tank touched.
	"""
	day = bon_day(order)
	for ge in frappe.get_all(
		"Gate Entry",
		filters={"order_doctype": "Order Bongkar", "order_ref": order.name, "status": ["!=", "Cancelled"]},
		fields=["name", "in_date"],
	):
		if ge.in_date != day:
			frappe.db.set_value("Gate Entry", ge.name, "in_date", day)
	for row in _rows(order):
		c = row.get("container")
		if c and frappe.db.get_value("Container", c, "last_order_bongkar") == order.name:
			frappe.db.set_value("Container", c, "in_date", day)
		_resync(c)


def follow_muat(order) -> None:
	"""A submitted Order Muat's Tanggal Muat was corrected: move the departure with it."""
	day = bon_day(order)
	for ge in frappe.get_all(
		"Gate Entry", filters={"order_muat": order.name, "status": ["!=", "Cancelled"]},
		fields=["name", "container_no", "out_date"],
	):
		if ge.out_date != day:
			frappe.db.set_value("Gate Entry", ge.name, "out_date", day)
	for row in _rows(order):
		c = row.get("container")
		tank = c and frappe.db.get_value("Container", c, ["last_order_muat", "status"], as_dict=True)
		if tank and tank.last_order_muat == order.name and tank.status == "Gate_Out":
			frappe.db.set_value("Container", c, "out_date", day)
		_resync(c)


def _resync(container) -> None:
	if not container or not frappe.db.exists("Container", container):
		return
	from container_depot import storage_charge

	storage_charge.sync(container)
