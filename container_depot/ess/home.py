"""ESS PWA home-screen endpoint — the one GET behind the Beranda redesign.

Read-only, and deliberately *lean*: this runs on every app open, on a depot handset, so
it never loads a container list. Every number here is a ``COUNT`` (plus one row for the
oldest item in the queue), scoped to the caller's depots.

Two sections, and they answer two different questions:

* ``today``   — "what has the depot done since midnight, and what is still hanging off
  it" — the four tiles at the top of Beranda. Each pairs a headline count with the one
  sub-count that says whether the work behind it is finished.
* ``waiting`` — "what is waiting on ME" — one row per queue that has anything in it, with
  the age of its OLDEST item. Age is the whole point of the section: three cleaning orders
  raised a minute ago are not a problem, one raised at the start of the shift is.

Both sections are gated on ``allowed_menu()`` exactly like
:func:`container_depot.ess.inventory.get_dashboard_summary` — a section is present only
when the caller may open the page behind it, so Team Cleaning gets the cleaning queue and
none of the gate counts. Deriving the gate from the menu (rather than from a second role
table) is what keeps Beranda from drifting away from what the tiles can actually open.

Text lives in the front-end (``frontend/src/utils/labels.js``); this returns numbers and
keys only.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds, today

from container_depot.api import _require_authenticated_user
from container_depot.container_depot.container_status import DONE_CLEANING
from container_depot.container_depot.user_branch import get_user_depots

# Cleaning statuses that mean nobody has touched the tank yet. `Service Setup` is the
# state a freshly raised order sits in before its services are picked, so it counts as
# not-started just as much as `Pending` does.
CLEANING_NOT_STARTED = ("Service Setup", "Pending")

# At most this many rows in "Menunggu Anda". A supervisor holds every menu and would
# otherwise get a wall of rows on the screen that exists to say what is urgent — and
# the rows are already sorted oldest-first, so the cut falls on the least urgent.
#
# Naik dari enam ke delapan pada 2026-09-09, saat antrean review Cleaning & M&R dan
# jadwal terlambat ikut masuk: dengan sepuluh baris yang mungkin, enam berarti SPV yang
# memegang semua menu kehilangan antrean-antrean termuda tanpa pernah tahu ia ada.
MAX_WAITING = 8


# Kartu "Hari ini" yang boleh diminta, dan menu yang menjaga masing-masing. Operator
# memilih sendiri empat kartu mana yang tampil (localStorage, lihat frontend
# utils/homeTiles.js), lalu MENGIRIM pilihannya ke sini — bukan supaya server tahu
# selera orang, tapi supaya ia tidak menghitung tujuh angka yang tidak akan dibaca.
# Modul ini berjanji lean di baris pertama docstring-nya, dan janji itu yang membuat
# katalog boleh tumbuh sampai sebelas tanpa membebani pembukaan aplikasi.
TILE_MENU = {
	"gateIn": "gate",
	"gateOut": "gate",
	"eirOpen": "eir",
	"eirReview": "eir",
	"cleaning": "cleaning",
	"mr": "mr",
	"monitor": "monitor",
	"schedule": "schedule",
	"survey": "surveyList",
	"lowering": "posFix",
	"unlocated": "tankPos",
}

# Yang tampil untuk akun yang belum pernah memilih — persis empat kartu yang ada sebelum
# pemilihan ini dibuat, jadi tidak ada handset yang layarnya berubah tanpa diminta.
DEFAULT_TILES = ("gateIn", "gateOut", "eirReview", "cleaning")


def _wanted_tiles(tiles, menu: set) -> set:
	"""Kartu yang diminta klien, disaring permission. Param kosong = empat bawaan.

	Menu tetap yang berkuasa: kunci yang dikirim tanpa hak menunya dibuang diam-diam,
	sama seperti tab bar bawah. Klien hanya boleh memilih dari apa yang sudah boleh
	dibukanya.
	"""
	if isinstance(tiles, str):
		asked = [t.strip() for t in tiles.split(",") if t.strip()]
	elif isinstance(tiles, (list, tuple)):
		asked = [str(t).strip() for t in tiles if str(t).strip()]
	else:
		asked = []
	# "undefined" / "null" — lihat catatan _NOT_A_VALUE di tank_survey.py: frappe-ui
	# sempat mengirim string itu untuk param yang tidak diisi.
	asked = [t for t in asked if t.lower() not in ("undefined", "null", "none")]
	if not asked:
		asked = list(DEFAULT_TILES)
	return {t for t in asked if TILE_MENU.get(t) in menu}


def _scoped(filters: dict, allowed) -> dict:
	"""Add the caller's depot scope to a filter dict. ``allowed`` is None = unrestricted."""
	if allowed is not None:
		filters = {**filters, "depot": ["in", allowed or [""]]}
	return filters


def _age_minutes(value) -> int | None:
	"""Whole minutes since ``value``, or None when there is no timestamp to measure."""
	if not value:
		return None
	return max(0, int(time_diff_in_seconds(now_datetime(), value) // 60))


def _queue(key: str, doctype: str, filters: dict, *, ref_field="container_no", time_field="creation"):
	"""One "Menunggu Anda" row, or None when the queue is empty.

	``ref`` is filled only when the queue holds exactly ONE item: naming the container is
	what turns "1 EIR menunggu review" into something an operator recognises, and naming
	one of five would be picking a favourite.
	"""
	count = frappe.db.count(doctype, filters)
	if not count:
		return None
	oldest = frappe.get_all(
		doctype,
		filters=filters,
		fields=[ref_field, time_field],
		order_by=f"{time_field} asc",
		limit=1,
	)
	row = oldest[0] if oldest else {}
	return {
		"key": key,
		"count": count,
		"ref": row.get(ref_field) if count == 1 else None,
		"age": _age_minutes(row.get(time_field)),
	}


def _active_booking_codes(allowed) -> list:
	"""Booking Codes that are cleared and still waiting for their truck at the barrier.

	``Active`` is the payment-cleared signal (``api.validate_qr``), so these are exactly
	the movements the gate is expecting today — and an expired one is not waiting for
	anybody, whether or not the expiry job has run yet.

	Raw SQL because Booking Code carries no ``depot`` of its own: the scope lives on its
	Container Booking, and one join is cheaper than pulling every booking name in the
	branch just to build an ``in`` list.
	"""
	where = ["bc.state = 'Active'", "(bc.expires_at is null or bc.expires_at >= now())"]
	args: dict = {}
	if allowed is not None:
		if not allowed:
			return []
		where.append("b.depot in %(depots)s")
		args["depots"] = allowed
	return frappe.db.sql(
		f"""
		select bc.container_no, bc.direction, bc.issued_at
		from `tabBooking Code` bc
		inner join `tabContainer Booking` b on b.name = bc.booking
		where {' and '.join(where)}
		order by bc.issued_at asc
		""",
		args,
		as_dict=True,
	)


@frappe.whitelist(methods=["GET"])
def get_home_summary(tiles=None):
	"""GET /api/v1/ess/home-summary — ``{success, menu, today, waiting}``.

	``tiles`` adalah daftar kunci kartu yang akan ditampilkan Beranda (dipisah koma, lihat
	``TILE_MENU``). Hanya kartu itu yang dihitung; tanpa param, empat kartu bawaan. Angka
	yang sudah terlanjur dihitung untuk "Menunggu Anda" dipakai ulang, tidak dihitung dua
	kali.

	A caller with no field role gets ``{"success": True, "menu": []}`` and nothing else:
	the PWA is open to them, it is simply empty, and Beranda already has a card that says
	why.
	"""
	from container_depot.ess.context import allowed_menu

	_require_authenticated_user()
	menu = set(allowed_menu())
	if not menu:
		return {"success": True, "menu": []}

	from container_depot.container_depot import (
		container_position,
		eir,
		mr,
		schedule,
		tank_survey,
	)

	allowed = get_user_depots()  # None = unrestricted; [] = no depot at all
	out = {"success": True, "menu": sorted(menu), "today": {}, "waiting": []}
	today_counts = out["today"]
	waiting = out["waiting"]
	want = _wanted_tiles(tiles, menu)

	# --- Gate: what came in and went out since midnight -----------------------------
	# Read from the Container Activity log rather than from the gate documents, same as
	# the Desk dashboard: it is the one table that records a movement per tank whichever
	# door it came through.
	if "gate" in menu:
		if {"gateIn", "gateOut"} & want:
			act = _scoped({"activity_time": [">=", today()]}, allowed)
			if "gateIn" in want:
				today_counts["gate_in"] = frappe.db.count(
					"Container Activity", {**act, "activity_type": "Gate In"}
				)
			if "gateOut" in want:
				today_counts["gate_out"] = frappe.db.count(
					"Container Activity", {**act, "activity_type": "Gate Out"}
				)
		codes = _active_booking_codes(allowed)
		# Sub-count under "Tank keluar": bookings cleared to leave whose truck has not
		# arrived. The full list (both directions) is the gate's own queue row below.
		if "gateOut" in want:
			today_counts["booking_out"] = sum(1 for c in codes if c.direction == "Tank Out")
		if codes:
			waiting.append({
				"key": "bookingGate",
				"count": len(codes),
				"ref": codes[0].container_no if len(codes) == 1 else None,
				"age": _age_minutes(codes[0].issued_at),
			})

	# --- EIR: drafts to work, and the ones already done waiting on Admin Ops ---------
	if "eir" in menu:
		eir_open = _scoped(
			{"docstatus": 0, "inspection_type": "EIR-In", "status": ["!=", "Pending Review"]},
			allowed,
		)
		# In DAN Out, karena itulah isi layar yang dibuka kartu ini: "Diajukan Review" di PWA
		# adalah ``eir.list_review_eirs``, dan daftar itu tidak pernah memilah jenisnya. Kartu
		# ini sempat menghitung EIR-In saja, jadi sebuah EIR-Out yang menunggu Admin Ops duduk
		# di daftarnya tanpa pernah muncul di Beranda.
		eir_review = _scoped(
			{
				"docstatus": 0,
				"inspection_type": ["in", ["EIR-In", "EIR-Out"]],
				"status": "Pending Review",
			},
			allowed,
		)
		# "Belum EIR" under "Tank masuk": every tank that came in still owes one, and this
		# is the same list the EIR worklist opens on (``eir.list_pending_eirs``). Dihitung
		# juga untuk kartu "Tank masuk", yang memakainya sebagai sub-angka.
		if {"eirOpen", "gateIn"} & want:
			today_counts["eir_open"] = frappe.db.count("Inspection", eir_open)
		if "eirReview" in want:
			today_counts["eir_review"] = frappe.db.count("Inspection", eir_review)
			review_oldest = frappe.get_all(
				"Inspection", filters=eir_review, fields=["creation"], order_by="creation asc", limit=1
			)
			today_counts["eir_review_age"] = (
				_age_minutes(review_oldest[0].creation) if review_oldest else None
			)
		for row in (
			_queue("eirReview", "Inspection", eir_review),
			_queue("eirOpen", "Inspection", eir_open),
		):
			if row:
				waiting.append(row)
		# EIR-Out rides on the worklist rather than on a filter of our own: which tanks owe
		# an out-inspection is a question about their booking, not about the Inspection
		# table, and that answer lives in one place (``eir.list_pending_eir_out``).
		eir_out = eir.list_pending_eir_out(page_length=1)["total"]
		if "eirOpen" in want:
			today_counts["eir_out"] = eir_out
		if eir_out:
			waiting.append({"key": "eirOut", "count": eir_out, "ref": None, "age": None})

	# --- Cleaning: open orders, and how many nobody has started ---------------------
	if "cleaning" in menu:
		clean_idle = _scoped(
			{"status": ["in", CLEANING_NOT_STARTED], "docstatus": ["<", 2]}, allowed
		)
		if "cleaning" in want:
			clean_open = _scoped(
				{"status": ["not in", DONE_CLEANING], "docstatus": ["<", 2]}, allowed
			)
			today_counts["cleaning_open"] = frappe.db.count("Cleaning Order", clean_open)
			today_counts["cleaning_idle"] = frappe.db.count("Cleaning Order", clean_idle)
		row = _queue("cleaningIdle", "Cleaning Order", clean_idle)
		if row:
			waiting.append(row)
		# Sudah dicuci, dikirim dari lapangan, menunggu Adm Ops menutupnya — antrean yang
		# sama bentuknya dengan "EIR diajukan review" di atas. Tanpa baris ini Adm Ops yang
		# memegang ketiga menu melihat EIR-nya di beranda dan dua sisanya tidak.
		row = _queue(
			"cleaningReview",
			"Cleaning Order",
			_scoped({"status": "Pending Review", "docstatus": 0}, allowed),
		)
		if row:
			waiting.append(row)

	# --- M&R: the queue that is waiting on a human decision, not on a wrench ---------
	if "mr" in menu:
		mr_approval = _scoped({"status": "Pending Approval"}, allowed)
		if "mr" in want:
			# Sama dengan angka yang dibaca dashboard Monitor (ess/inventory.py): satu
			# sumber untuk "berapa order M&R yang masih berjalan", bukan dua filter yang
			# lambat laun berselisih.
			today_counts["mr_open"] = mr.list_open_mr_orders(page_length=1)["total"]
			today_counts["mr_approval"] = frappe.db.count("Repair Order", mr_approval)
		row = _queue("mrApproval", "Repair Order", mr_approval)
		if row:
			waiting.append(row)
		# Perbaikannya selesai, menunggu diperiksa & ditutup di Desk — lihat catatan di
		# antrean review Cleaning di atas.
		row = _queue("mrReview", "Repair Order", _scoped({"status": "Pending Review"}, allowed))
		if row:
			waiting.append(row)

	# --- Monitor: berapa tank yang ada di depo sekarang ------------------------------
	# COUNT lurus, bukan get_inventory_summary: yang terakhir menarik SELURUH baris
	# Container untuk membaginya per bucket, dan itu harga yang tidak boleh dibayar setiap
	# aplikasi dibuka. Kartu ini cuma butuh totalnya; pembagiannya ada di layar Monitor.
	if "monitor" in want:
		from container_depot.ess.inventory import EXCLUDED_FROM_INVENTORY

		today_counts["depot_total"] = frappe.db.count(
			"Container", _scoped({"status": ["not in", EXCLUDED_FROM_INVENTORY]}, allowed)
		)

	# --- Jadwal: hari ini, dan yang sudah lewat tapi belum beres ---------------------
	if "schedule" in menu:
		if "schedule" in want:
			day = schedule.schedule_day()
			items = day.get("items") or []
			today_counts["schedule_today"] = len(items)
			today_counts["schedule_open"] = sum(1 for c in items if not c.get("done"))
		# Pekerjaan terencana dari hari-hari SEBELUMNYA yang masih terbuka. Ini satu-satunya
		# antrean yang tidak bisa dilihat dari layar mana pun kecuali dengan mundur ke
		# tanggalnya: truk yang kemarin tidak datang tidak muncul di daftar hari ini, dan
		# tidak ada dokumen yang berubah status untuk memberitahu siapa pun.
		#
		# Aturannya diambil dari kalender, bukan ditulis ulang di sini — `_overdue` yang sama
		# yang menggambar spanduk "dari kemarin" di layar Jadwal, jadi angka di beranda tidak
		# bisa berselisih dengan angka di halamannya.
		overdue = schedule.overdue_summary()
		if overdue.get("count"):
			waiting.append({
				"key": "scheduleOverdue",
				"count": overdue["count"],
				"ref": None,
				# Umur dihitung dari hari tertua yang tertinggal — itu yang menaruhnya di
				# atas antrean lain, dan memang di situ tempatnya.
				"age": _age_minutes(overdue.get("since")),
			})

	# --- Survey Order hari ini ------------------------------------------------------
	if "survey" in want:
		today_counts["survey_today"] = tank_survey.list_survey_orders(page_length=1)["total"]

	# --- Survey family + Letak Tank -------------------------------------------------
	# Counts only: each of these worklists decides its own scope and ordering (a tank is
	# "waiting to be lowered" because of its Survey Order's day, not because of a status
	# on a row), so the totals come from the worklists themselves. Angkanya dipakai dua
	# kali — baris antrean di bawah DAN kartunya — tapi dihitung sekali.
	if "posFix" in menu:
		total = tank_survey.list_waiting_lowering(page_length=1)["total"]
		if "lowering" in want:
			today_counts["lowering"] = total
		if total:
			waiting.append({"key": "lowering", "count": total, "ref": None, "age": None})
	if "surveyPos" in menu:
		total = tank_survey.list_ready_to_survey(page_length=1)["total"]
		if total:
			waiting.append({"key": "surveyReady", "count": total, "ref": None, "age": None})
	if "tankPos" in menu:
		# Kartunya menghitung SEMUA tank tanpa letak; antreannya tidak, dan itu disengaja.
		# Sebuah yard menyimpan ratusan tank yang letaknya tidak pernah dicatat karena memang
		# belum ada yang menanyakannya, jadi "17 tank belum ada letaknya" muncul setiap pagi
		# tanpa menyuruh siapa pun berbuat apa-apa — angka yang cuma menua di tempatnya sampai
		# seluruh bagian ini berhenti dibaca. Yang layak masuk antrean hanya tank yang surveinya
		# sudah dijadwalkan tapi letaknya belum (atau basi) dicatat: itu punya tenggat, punya
		# orang, dan hilang sendiri begitu satu bacaan masuk.
		#
		# Aturannya tidak ditulis ulang di sini — antrean yang sama persis dengan tab "Perlu
		# Dicek" di layar Letak Tank (container_position.open_position_orders).
		if "unlocated" in want:
			today_counts["unlocated"] = container_position.search_containers(
				page_length=1, only_unlocated=1
			)["total"]
		total = container_position.open_position_orders(page_length=1)["total"]
		if total:
			waiting.append({"key": "positionOrder", "count": total, "ref": None, "age": None})

	# Oldest first — the section answers "what has been waiting longest", so a queue with
	# no age at all (the survey worklists, which are dated rather than aged) sorts under
	# the timed ones rather than above them.
	waiting.sort(key=lambda r: (r["age"] is None, -(r["age"] or 0), -r["count"]))
	del waiting[MAX_WAITING:]
	return out
