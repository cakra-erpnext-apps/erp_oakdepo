"""ESS PWA read endpoints — Feature F1 (Tank Inventory & Live Status).

All endpoints are GET, authenticated (Guest rejected via the shared
``_require_authenticated_user`` guard), and **permission-aware**: container
reads go through ``frappe.get_list`` / ``frappe.has_permission``, so the
Custom DocPerm matrix seeded by ``install.py`` *and* any ``User Permission``
(e.g. depot scoping on ``Container.depot``) filter the results automatically.
There is no permission logic in the PWA.

Status is **derived server-side** here — the raw ``Container.status`` Select
carries the full lifecycle (normalised in B0: duplicate removed, portal states
added), but the Monitor UI groups tanks by their concrete order state so a field
observer sees the work pipeline. :func:`derive_status` collapses the raw status plus
the tank's Cleaning/M&R order state into five buckets — available / draft / pending /
in_progress / gate_out — classifying by the most-advanced order state it carries.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, date_diff, getdate, today

from container_depot.api import _require_authenticated_user
from container_depot.ess.guard import require_menu
from container_depot.container_depot import container_activity, container_status
from container_depot.container_depot.user_branch import get_user_depots

# Canonical Monitor status buckets — order-state centric so a field observer sees the
# concrete work state per container (keys are stable; labels live in the front-end).
BUCKETS = ("available", "draft", "pending", "in_progress", "gate_out")

# Raw statuses that are NOT physically in the depot yet and must be excluded from
# live inventory counts/lists. `Booked` = a tank reserved by an Container Booking
# whose Container master was created at booking time but has not yet gated in.
EXCLUDED_FROM_INVENTORY = ("Booked",)

# Order states grouped into the Monitor buckets. A container is classified by the
# MOST-ADVANCED order state it carries (in_progress > pending > draft), across Cleaning
# Order + Repair Order (M&R). No open order at all -> `available`.
#   in_progress ("Dikerjakan") = a started job     (start_cleaning / start_repair)
#   pending     ("Pending")    = waiting to be run (queued / awaiting or post approval)
#   draft       ("Draft")      = M&R created, not yet submitted for approval
IN_PROGRESS_CLEANING = ("In_Progress",)
IN_PROGRESS_REPAIR = ("In Progress",)
PENDING_CLEANING = ("Pending",)
PENDING_REPAIR = ("Pending Approval", "Approved")
DRAFT_REPAIR = ("Draft",)

# Container.status is presence-based (Booked / In_Depot / Available / Gate_Out).
# `Gate_Out` is terminal; everything else with no open order maps to `available`.
_GATE_OUT_RAW = {"Gate_Out"}

# Fields surfaced in the tank list (kept lean for the < 2s/1000-tank target).
_LIST_FIELDS = [
	"name",
	"container_no",
	"container_type",
	"principal",
	"depot",
	"yard_zone",
	"current_location",
	"status",
	"last_order_bongkar",
]

# Tiga kelompok yang dibaca layar Monitor. Lima bucket di atas menjawab "pekerjaan apa yang
# menahan tank ini"; kelompok menjawab pertanyaan yang lebih dulu ditanyakan orang yang berdiri
# di yard: "tank ini sedang dikerjakan, siap, atau sudah keluar". Draft dan Pending bukan
# keadaan tank yang berbeda bagi pengamat — ketiganya sama-sama berarti ada yang belum selesai,
# jadi ketiganya satu kelompok dan lencana barisnya yang menyebut persisnya.
# Kunci kelompok sengaja TIDAK memakai ulang nama bucket "in_progress". Sempat begitu, dan
# akibatnya filter `status=in_progress` — yang dikirim deep-link KPI dashboard dan berarti
# "pekerjaan yang benar-benar sedang berjalan" — diam-diam ikut menarik draft dan pending,
# karena satu kata menjawab dua pertanyaan. "available" dan "gate_out" boleh sama: di kedua
# sisi isinya persis baris yang sama.
GROUPS = ("working", "available", "gate_out")
_GROUP_OF = {
	"draft": "working",
	"pending": "working",
	"in_progress": "working",
	"available": "available",
	"gate_out": "gate_out",
}


def _apply_user_depot_scope(filters, depot):
	"""Intersect a Container query's depot filter with the user's allowed depots.

	Container has no Branch field, so the native Branch User Permission does not
	scope it — we filter on ``depot`` explicitly. Returns the (possibly updated)
	filters dict, or None to signal 'no results' (the requested depot is outside
	the user's branch scope)."""
	allowed = get_user_depots()
	if allowed is None:
		if depot:
			filters["depot"] = depot
		return filters
	if depot:
		if depot not in allowed:
			return None
		filters["depot"] = depot
	else:
		filters["depot"] = ["in", allowed]
	return filters


def derive_status(raw_status, in_progress=False, pending=False, draft=False):
	"""Collapse a raw Container.status + its order-state signals into one Monitor bucket.

	Precedence (most-advanced order state wins): a gated-out tank is terminal; then a
	started job (`in_progress`); then a queued/awaiting job (`pending`); then an
	unsubmitted M&R (`draft`); else the tank has no open order -> `available` (includes a
	tank just gated in with nothing raised on it yet).
	"""
	if raw_status in _GATE_OUT_RAW:
		return "gate_out"
	if in_progress:
		return "in_progress"
	if pending:
		return "pending"
	if draft:
		return "draft"
	return "available"


# Order status -> (bucket state) per doctype, so a row can also name WHICH order drives it.
_CLEANING_STATE = {s: "in_progress" for s in IN_PROGRESS_CLEANING}
_CLEANING_STATE.update({s: "pending" for s in PENDING_CLEANING})
_REPAIR_STATE = {s: "in_progress" for s in IN_PROGRESS_REPAIR}
_REPAIR_STATE.update({s: "pending" for s in PENDING_REPAIR})
_REPAIR_STATE.update({s: "draft" for s in DRAFT_REPAIR})
_STATE_RANK = {"draft": 1, "pending": 2, "in_progress": 3}


def _driving_orders(names):
	"""Map container -> the order that drives its Monitor bucket: the most-advanced
	(in_progress > pending > draft) Cleaning/M&R order, as
	``{"state", "kind", "doctype", "name", "status"}``. Restricted to ``names``."""
	if not names:
		return {}
	rows = []
	for r in frappe.get_all(
		"Cleaning Order",
		filters={"container": ["in", names], "status": ["in", list(_CLEANING_STATE)]},
		fields=["name", "container", "status"],
	):
		rows.append((r.container, _CLEANING_STATE[r.status], "Cleaning", "Cleaning Order", r.name, r.status))
	for r in frappe.get_all(
		"Repair Order",
		filters={"container": ["in", names], "status": ["in", list(_REPAIR_STATE)]},
		fields=["name", "container", "status"],
	):
		rows.append((r.container, _REPAIR_STATE[r.status], "M&R", "Repair Order", r.name, r.status))
	# EIR yang SUDAH DISENTUH. Sebuah EIR-In draft lahir sendiri bersama tank-nya, jadi
	# menghitung setiap draft berarti menyebut seluruh isi depo "sedang dikerjakan" — tapi
	# `work_started_on` hanya ada kalau seseorang benar-benar membuka dan memulainya, dan itu
	# ukuran yang sudah dipakai eir.py untuk membedakan EIR berisi pekerjaan dari EIR kosong.
	#
	# Sebelum ini tank dengan EIR berjalan tampil "Available" di Monitor padahal
	# container_status menahannya di In_Depot dan gate menolak melepasnya — dua layar yang
	# menjawab pertanyaan yang sama dengan jawaban berbeda.
	for r in frappe.get_all(
		"Inspection",
		filters={"container": ["in", names], "docstatus": 0, "work_started_on": ["is", "set"]},
		fields=["name", "container", "inspection_type"],
	):
		rows.append((r.container, "draft", "EIR", "Inspection", r.name, r.inspection_type or "EIR"))
	out = {}
	for container, state, kind, doctype, name, status in rows:
		cur = out.get(container)
		if cur is None or _STATE_RANK[state] > _STATE_RANK[cur["state"]]:
			out[container] = {"state": state, "kind": kind, "doctype": doctype, "name": name, "status": status}
	return out


def _order_ref(drv):
	"""The frontend link payload for a driving order (or None)."""
	if not drv:
		return None
	return {"kind": drv["kind"], "doctype": drv["doctype"], "name": drv["name"], "status": drv["status"]}


def _last_activity(names):
	"""container -> aktivitas TERAKHIRNYA ``{type, summary, time, by, ref_doctype, ref_name}``.

	Satu kueri untuk seluruh halaman, lewat turunan ``max(activity_time)`` — bukan satu kueri
	per tank. Daftar Monitor menyapu ratusan container sekaligus dan baris ketiganya ("Mulai
	perbaikan · 12 mnt lalu · Rudi") ada di setiap baris, jadi versi per-tank akan membayar
	ratusan query untuk satu layar yang cuma dibaca sekilas.

	Dipakai tiga kali dari satu hasil: kalimat baris, filter periode ("aktivitas hari ini"),
	dan urutan (teraktif / paling lama diam). Ketiganya HARUS memakai jam yang sama — kalau
	tidak, sebuah tank bisa lolos filter "hari ini" sambil menampilkan aktivitas minggu lalu.
	"""
	if not names:
		return {}
	rows = frappe.db.sql(
		"""
		select a.container, a.activity_type, a.summary, a.activity_time, a.performed_by,
		       a.reference_doctype, a.reference_name
		  from `tabContainer Activity` a
		  join (
		        select container, max(activity_time) as t
		          from `tabContainer Activity`
		         where container in %(names)s
		         group by container
		       ) m on m.container = a.container and m.t = a.activity_time
		 where a.container in %(names)s
		""",
		{"names": tuple(names)},
		as_dict=True,
	)
	out = {}
	for r in rows:
		# Dua aktivitas berjam sama persis: yang pertama menang, sekadar supaya hasilnya tetap.
		out.setdefault(r.container, {
			"type": r.activity_type,
			"summary": r.summary,
			"time": str(r.activity_time) if r.activity_time else None,
			"by": r.performed_by,
			"ref_doctype": r.reference_doctype,
			"ref_name": r.reference_name,
		})
	return out


def _clean(value):
	"""``None`` untuk filter yang datang sebagai "" / "undefined" / "null" dari klien."""
	value = (value or "").strip()
	return None if not value or value.lower() in ("undefined", "null", "none") else value


def _scan(search=None):
	"""Setiap container yang boleh dilihat pemanggil, lengkap dengan bucket, kelompok, dan
	aktivitas terakhirnya — SEBELUM filter depot / prinsipal / periode / status dipasang.

	Satu pemindaian ini yang dipakai daftar DAN penghitung faset di sheet filter. Kalau
	keduanya memindai sendiri-sendiri, tombol "Terapkan · 96 tank" bisa menjanjikan angka yang
	tidak sama dengan isi daftar yang muncul sesudahnya — dan yang salah tidak akan ketahuan
	karena keduanya sama-sama terlihat masuk akal.
	"""
	filters = {"status": ["not in", EXCLUDED_FROM_INVENTORY]}
	scoped = _apply_user_depot_scope(filters, None)
	if scoped is None:
		return []
	or_filters = None
	search = _clean(search)
	if search:
		# Nomor tank ATAU nomor bon: yang dipegang orang yang mencari belum tentu tanknya —
		# sering justru selembar bon bongkar dengan nomor tank yang tidak terbaca lagi.
		or_filters = {
			"container_no": ["like", f"%{search}%"],
			"last_order_bongkar": ["like", f"%{search}%"],
		}

	rows = frappe.get_list(
		"Container",
		filters=scoped,
		or_filters=or_filters,
		fields=_LIST_FIELDS,
		order_by="container_no asc",
		limit_page_length=0,
	)
	names = [r.name for r in rows]
	driving = _driving_orders(names)
	activity = _last_activity(names)

	out = []
	for r in rows:
		drv = driving.get(r.name)
		st = (drv or {}).get("state")
		bucket = derive_status(r.status, st == "in_progress", st == "pending", st == "draft")
		out.append({
			"name": r.name,
			"container_no": r.container_no,
			"container_type": r.container_type,
			"principal": r.principal,
			"depot": r.depot,
			"location": r.current_location,
			"status": bucket,
			"group": _GROUP_OF[bucket],
			"raw_status": r.status,  # exact Container.status (drives the gate-out action eligibility)
			"order_bongkar": r.last_order_bongkar,
			# Which order put the tank in this bucket (draft/pending/in_progress) —
			# lets the UI say "Draft M&R" and link straight to the order.
			"order": _order_ref(drv) if bucket in ("draft", "pending", "in_progress") else None,
			"last_activity": activity.get(r.name),
		})
	return out


# Periode aktivitas -> berapa hari ke belakang. `None` = tanpa batas.
_PERIODS = {"today": 0, "7d": 7, "all": None}


def _passes(row, depot=None, principal=None, status=None, cutoff=None):
	"""Apakah satu baris lolos filter yang dipilih? Dipakai daftar dan penghitung faset."""
	if depot and row["depot"] != depot:
		return False
	if principal and row["principal"] != principal:
		return False
	if status and status not in (row["status"], row["group"]):
		return False
	if cutoff is not None:
		la = row.get("last_activity") or {}
		if not la.get("time") or la["time"][:10] < cutoff:
			return False
	return True


def _cutoff(period):
	"""Tanggal terawal yang masih dihitung "punya aktivitas", atau None untuk semua waktu."""
	period = _clean(period) or "all"
	days = _PERIODS.get(period, None)
	if days is None:
		return None
	return str(getdate(add_to_date(today(), days=-days)))


# Urutan daftar. Kuncinya mengembalikan tuple: elemen pertama memaksa baris tanpa aktivitas
# ke ujung yang benar (paling bawah saat mengurut keaktifan, paling atas saat mencari yang
# paling lama diam — sebuah tank yang tidak pernah tercatat apa-apa adalah yang PALING diam,
# bukan yang paling baru).
def _sort_key(sort):
	if sort == "number":
		return lambda r: (r.get("container_no") or r["name"] or "",)
	if sort == "idle":
		return lambda r: (bool((r.get("last_activity") or {}).get("time")),
		                  (r.get("last_activity") or {}).get("time") or "")
	return lambda r: (not (r.get("last_activity") or {}).get("time"),
	                  _desc((r.get("last_activity") or {}).get("time")))


def _desc(value):
	"""Kunci urut menurun untuk string tanggal, tanpa `reverse=True` yang akan ikut membalik
	elemen pertama tuple (penanda "tidak punya aktivitas") dan menaruhnya di tempat salah."""
	return tuple(-ord(c) for c in (value or ""))


@frappe.whitelist(methods=["GET"])
def get_inventory_summary(depot=None):
	"""Status-count header, depot-scoped.

	GET /api/v1/ess/inventory-summary
	"""
	require_menu("monitor")

	filters = {"status": ["not in", EXCLUDED_FROM_INVENTORY]}
	scoped = _apply_user_depot_scope(filters, depot)
	if scoped is None:
		return {
			"success": True,
			"counts": {b: 0 for b in BUCKETS},
			"groups": {g: 0 for g in GROUPS},
			"total": 0,
		}
	filters = scoped

	# Permission-aware: User Permissions on Depot (and DocPerms) filter this.
	containers = frappe.get_list(
		"Container",
		filters=filters,
		fields=["name", "status"],
		limit_page_length=0,
	)
	names = [c.name for c in containers]
	driving = _driving_orders(names)

	counts = {b: 0 for b in BUCKETS}
	groups = {g: 0 for g in GROUPS}
	for c in containers:
		st = (driving.get(c.name) or {}).get("state")
		bucket = derive_status(c.status, st == "in_progress", st == "pending", st == "draft")
		counts[bucket] += 1
		groups[_GROUP_OF[bucket]] += 1

	return {
		"success": True,
		"counts": counts,
		# Empat pil di puncak Monitor: Semua + ketiga kelompok ini.
		"groups": groups,
		"total": len(names),
	}


@frappe.whitelist(methods=["GET"])
def get_tank_list(
	search=None, principal=None, status=None, depot=None,
	today=0, period=None, sort=None, start=0, page_length=50,
):
	"""Searchable / filterable / paginated tank list with derived status.

	A custom endpoint (not /api/resource) is required because the status filter
	and the rows themselves expose the *derived* bucket, which has no column to
	filter on server-side. Container reads remain permission-aware.

	``status`` menerima bucket presisi (``draft`` / ``pending`` / …) MAUPUN kelompok
	(``in_progress`` / ``available`` / ``gate_out``) — pil di puncak layar mengirim yang kedua,
	deep-link lama dari dashboard mengirim yang pertama, dan keduanya harus tetap jalan.

	GET /api/v1/ess/tank-list
	"""
	require_menu("monitor")

	start = cint(start)
	page_length = cint(page_length) or 50
	status = _clean(status)
	if status and status not in BUCKETS and status not in GROUPS:
		frappe.throw(frappe._("Invalid status filter: {0}").format(status), frappe.ValidationError)

	depot = _clean(depot)
	if depot:
		allowed = get_user_depots()
		if allowed is not None and depot not in allowed:
			return {"success": True, "total": 0, "start": start, "page_length": page_length, "items": []}
	# `today=1` adalah bentuk lama parameter ini; periode yang lebih kaya menggantikannya.
	period = _clean(period) or ("today" if cint(today) else "all")
	cutoff = _cutoff(period)

	principal = _clean(principal)
	# Disaring dua kali dari satu pemindaian: sekali TANPA pil status (itu yang dihitung
	# keempat pil di puncak layar dan kepala tiap kelompok), sekali dengan (itu isi daftarnya).
	# Kalau angka pil datang dari endpoint lain, ia akan menghitung dunia yang sedikit berbeda
	# dari daftar di bawahnya — dan yang membaca tidak punya cara tahu yang mana yang benar.
	scoped = [
		r for r in _scan(search)
		if _passes(r, depot=depot, principal=principal, cutoff=cutoff)
	]
	groups = {g: 0 for g in GROUPS}
	for r in scoped:
		groups[r["group"]] += 1

	rows = [r for r in scoped if _passes(r, status=status)]
	rows.sort(key=_sort_key(_clean(sort) or "activity"))

	return {
		"success": True,
		"total": len(rows),
		# Tanpa pil status: angka "Semua" dan tiap kelompok, di bawah filter yang sama.
		"all": len(scoped),
		"groups": groups,
		"start": start,
		"page_length": page_length,
		"items": rows[start : start + page_length],
	}


@frappe.whitelist(methods=["GET"])
def get_tank_facets(search=None, principal=None, status=None, depot=None, period=None):
	"""Berapa tank di balik tiap pilihan di sheet filter, plus total untuk tombol Terapkan.

	Tiap faset dihitung dengan pilihannya SENDIRI diabaikan — itu yang membuat angka di
	sebelah "OAK1" berarti "kalau depot diganti ke OAK1", bukan "0" hanya karena depot lain
	sedang dipilih. Total di tombol Terapkan justru memakai semua filter sekaligus, karena ia
	menjanjikan isi daftar yang akan muncul.

	GET /api/v1/ess/tank-facets
	"""
	require_menu("monitor")

	principal = _clean(principal)
	depot = _clean(depot)
	status = _clean(status)
	cutoff = _cutoff(period)
	rows = _scan(search)

	def count(**skip):
		f = {"depot": depot, "principal": principal, "status": status, "cutoff": cutoff}
		f.update(skip)
		return [r for r in rows if _passes(r, **f)]

	by_depot, by_principal = {}, {}
	for r in count(depot=None):
		if r["depot"]:
			by_depot[r["depot"]] = by_depot.get(r["depot"], 0) + 1
	for r in count(principal=None):
		if r["principal"]:
			by_principal[r["principal"]] = by_principal.get(r["principal"], 0) + 1

	groups = {g: 0 for g in GROUPS}
	for r in count(status=None):
		groups[r["group"]] += 1

	labels = (
		{c.name: c.customer_name for c in frappe.get_all(
			"Customer", filters={"name": ["in", list(by_principal)]}, fields=["name", "customer_name"]
		)} if by_principal else {}
	)
	depot_names = (
		{d.name: d.depot_name or d.name for d in frappe.get_all(
			"Depot", filters={"name": ["in", list(by_depot)]}, fields=["name", "depot_name"]
		)} if by_depot else {}
	)

	return {
		"success": True,
		# Angka di tombol "Terapkan": semua filter dipasang sekaligus.
		"total": len(count()),
		"all": len(rows),
		"groups": groups,
		"depots": [
			{"code": k, "name": depot_names.get(k) or k, "count": v}
			for k, v in sorted(by_depot.items(), key=lambda kv: (-kv[1], kv[0]))
		],
		"principals": [
			{"name": k, "label": labels.get(k) or k, "count": v}
			for k, v in sorted(by_principal.items(), key=lambda kv: (-kv[1], kv[0]))
		],
	}


@frappe.whitelist(methods=["GET"])
def list_container_principals():
	"""Distinct principals (Tank Owners) that have at least one in-depot container in the
	caller's branch scope — drives the Monitor Container principal filter.

	GET /api/v1/ess/container-principals
	"""
	require_menu("monitor")
	filters = {"status": ["not in", EXCLUDED_FROM_INVENTORY], "principal": ["is", "set"]}
	scoped = _apply_user_depot_scope(filters, None)
	if scoped is None:
		return {"principals": []}
	names = sorted({n for n in frappe.get_all("Container", filters=scoped, pluck="principal", distinct=True) if n})
	labels = (
		{c.name: c.customer_name for c in frappe.get_all(
			"Customer", filters={"name": ["in", names]}, fields=["name", "customer_name"]
		)} if names else {}
	)
	return {"principals": [{"name": n, "label": labels.get(n) or n} for n in names]}


@frappe.whitelist(methods=["GET"])
def list_user_depots():
	"""Active depots the caller may see (branch-scoped) — drives the Monitor depot filter.

	GET /api/v1/ess/user-depots. Returns [{code, name}]; empty when the user has no depot
	access. An unrestricted user (get_user_depots -> None) gets every active depot.
	"""
	require_menu("monitor")
	allowed = get_user_depots()
	filters = {"is_active": 1}
	if allowed is not None:
		if not allowed:
			return {"depots": []}
		filters["name"] = ["in", allowed]
	rows = frappe.get_all(
		"Depot", filters=filters, fields=["name", "depot_name"], order_by="name asc"
	)
	return {"depots": [{"code": d.name, "name": d.depot_name or d.name} for d in rows]}


@frappe.whitelist(methods=["GET"])
def get_tank_detail(container):
	"""Single-tank detail with derived status.

	GET /api/v1/ess/tank-detail
	"""
	require_menu("monitor")
	# Enforces both DocPerm read and any User Permission (depot) on this record.
	frappe.has_permission("Container", doc=container, ptype="read", throw=True)

	doc = frappe.get_doc("Container", container)
	drv = _driving_orders([doc.name]).get(doc.name)
	st = (drv or {}).get("state")
	bucket = derive_status(doc.status, st == "in_progress", st == "pending", st == "draft")

	return {
		"success": True,
		"name": doc.name,
		"container_no": doc.container_no,
		"container_type": doc.container_type,
		"size": doc.size,
		"principal": doc.principal,
		"depot": doc.depot,
		"yard_zone": doc.yard_zone,
		"current_location": doc.current_location,
		"last_cargo": doc.last_cargo,
		"capacity": doc.capacity,
		"tare_weight": doc.tare_weight,
		"max_gross_weight": doc.max_gross_weight,
		"last_test_date": str(doc.last_test_date) if doc.last_test_date else None,
		"serial_no": doc.serial_no,
		"eir_in_date": str(doc.eir_in_date) if doc.eir_in_date else None,
		"eir_out_date": str(doc.eir_out_date) if doc.eir_out_date else None,
		"status": bucket,
		"group": _GROUP_OF[bucket],
		"order": _order_ref(drv) if bucket in ("draft", "pending", "in_progress") else None,
		# Letak tank: catatan Container Position terakhir, apa adanya. Depot ini tidak
		# menyimpan peta yard (blok/baris/slot dihapus di patch v0_36), jadi yang bisa
		# ditampilkan adalah kalimat yang ditulis orang yang terakhir melihatnya — beserta
		# KAPAN ia menulisnya, karena letak berumur seminggu di yard yang sibuk adalah
		# tebakan, bukan jawaban.
		"location": doc.current_location,
		"location_updated_on": str(doc.location_updated_on) if doc.location_updated_on else None,
		"location_updated_by": doc.location_updated_by,
		"in_depot_days": _in_depot_days(doc),
		# Semua pekerjaan yang masih memegang tank ini, bukan cuma yang menentukan bucket —
		# aturannya milik container_status, satu-satunya definisi "belum selesai" di app ini.
		"open_orders": _open_orders(doc.name),
		"activities": container_activity.list_activity_history(
			page_length=5, container=doc.name
		)["items"],
	}


def _in_depot_days(doc):
	"""Sudah berapa hari tank ini di depo — dari EIR-In, jatuh ke aktivitas Gate In.

	``None`` kalau keduanya tidak ada: lebih baik kosong daripada "0 hari" untuk tank yang
	sebenarnya sudah sebulan berdiri di sana tanpa dokumen masuk.
	"""
	since = doc.eir_in_date
	if not since:
		since = frappe.db.get_value(
			"Container Activity",
			{"container": doc.name, "activity_type": "Gate In"},
			"activity_time",
			order_by="activity_time desc",
		)
	if not since:
		return None
	return max(0, date_diff(today(), getdate(since)))


def _open_orders(container):
	"""``container_open_orders`` + sejak kapan dan oleh siapa tiap pekerjaan berjalan.

	Jam mulainya diambil dari Container Activity yang menunjuk dokumen itu, bukan dari
	``creation``-nya: sebuah Repair Order bisa dibuat pagi dan baru benar-benar dikerjakan
	sore, dan yang ditanya orang yang membaca kartu "Proses aktif" adalah yang kedua.
	"""
	orders = container_status.container_open_orders(container)
	if not orders:
		return []
	names = [o["name"] for o in orders]
	started = {}
	for a in frappe.get_all(
		"Container Activity",
		filters={"container": container, "reference_name": ["in", names]},
		fields=["reference_name", "activity_time", "performed_by", "summary"],
		order_by="activity_time asc",  # yang PERTAMA menyentuh dokumen = mulainya
	):
		started.setdefault(a.reference_name, a)
	for o in orders:
		a = started.get(o["name"])
		o["since"] = str(a.activity_time) if a and a.activity_time else None
		o["by"] = a.performed_by if a else None
		o["note"] = a.summary if a else None
	return orders


def _count_active_job_containers(allowed) -> int:
	"""Distinct containers with work still open on them — Gap Analysis §4.8.4.

	The supervisor card people actually asked for. "±800 tanks in the yard" tells a
	supervisor nothing; "31 tanks with a job running" is the number they chase. Open
	means the same thing it means everywhere else in the app — see
	``container_status.container_open_orders``, which this deliberately mirrors: a draft
	EIR-In, or a Cleaning / M&R order not yet finished. EIR-Out is
	excluded there and excluded here.
	"""
	from container_depot.container_depot.container_status import (
		DONE_CLEANING,
		DONE_REPAIR,
	)

	scope = {} if allowed is None else {"depot": ["in", allowed or [""]]}
	containers = set(
		frappe.get_all(
			"Inspection",
			filters={**scope, "inspection_type": "EIR-In", "docstatus": 0},
			pluck="container",
		)
	)
	for doctype, done in (
		("Cleaning Order", DONE_CLEANING),
		("Repair Order", DONE_REPAIR),
	):
		containers |= set(
			frappe.get_all(
				doctype,
				filters={**scope, "status": ["not in", done], "docstatus": ["<", 2]},
				pluck="container",
			)
		)
	containers.discard(None)
	return len(containers)


@frappe.whitelist(methods=["GET"])
def get_dashboard_summary(depot=None):
	"""Aggregated home-dashboard payload, depot/branch-scoped — one GET so the PWA
	home screen loads every KPI in a single round-trip.

	Scoped to the caller's menu (§6): a section is present only when the caller may open
	the page behind it, so Team Cleaning gets the cleaning queue and not the gate counts.
	The mapping is DERIVED from ``allowed_menu()`` rather than from a second role table —
	one place decides who sees what, and the dashboard cannot drift away from the menu.

	Sections, each gated on its menu key:

	* ``counts`` / ``total`` — container per status bucket (``monitor``)
	* ``today`` — Gate In / Out (``gate``), EIR submitted today (``eir``)
	* ``pending`` — per-worklist open counts, one key per menu
	* ``active_jobs`` — tanks with a job running; supervisors only (every menu)

	A caller with no field role gets ``{"success": True, "menu": []}`` and nothing else —
	the PWA is open to them, it is simply empty.

	GET /api/v1/ess/dashboard-summary
	"""
	from container_depot.ess.context import MENU_KEYS, allowed_menu

	_require_authenticated_user()
	menu = set(allowed_menu())
	if not menu:
		return {"success": True, "menu": []}

	from container_depot.container_depot import cleaning, container_position, eir, mr, tank_survey

	allowed = get_user_depots()  # None = unrestricted; [] = no depot access
	out = {"success": True, "menu": sorted(menu)}

	# 1) Container-per-status buckets — reuse the summary.
	if "monitor" in menu:
		summary = get_inventory_summary(depot)
		out["counts"] = summary["counts"]
		out["total"] = summary["total"]

	# 2) Today's activity from the Container Activity log (depot-scoped).
	act_filters = {"activity_time": [">=", today()]}
	if allowed is not None:
		act_filters["depot"] = ["in", allowed or [""]]
	today_activity = {}
	if "gate" in menu:
		today_activity["gate_in"] = frappe.db.count(
			"Container Activity", {**act_filters, "activity_type": "Gate In"}
		)
		today_activity["gate_out"] = frappe.db.count(
			"Container Activity", {**act_filters, "activity_type": "Gate Out"}
		)
	if "eir" in menu:
		today_activity["eir"] = frappe.db.count(
			"Container Activity", {**act_filters, "activity_type": "Inspection (EIR)"}
		)
	if today_activity:
		out["today"] = today_activity

	# 3) Pending work — totals from the same worklists the PWA pages use (each is
	# branch-scoped internally; page_length=1 keeps the row fetch minimal — `total`
	# is the full count regardless).
	pending = {}
	if "eir" in menu:
		pending["eir_in"] = eir.list_pending_eirs(page_length=1)["total"]
		pending["eir_out"] = eir.list_pending_eir_out(page_length=1)["total"]
	if "cleaning" in menu:
		pending["cleaning"] = cleaning.list_open_cleaning_orders(page_length=1)["total"]
	if "mr" in menu:
		mr_appr_filters = {"status": "Pending Approval"}
		if allowed is not None:
			mr_appr_filters["depot"] = ["in", allowed or [""]]
		pending["mr_open"] = mr.list_open_mr_orders(page_length=1)["total"]
		pending["mr_approval"] = frappe.db.count("Repair Order", mr_appr_filters)
	# The two halves swapped teams when the flow was reversed (lowering first, survey second),
	# so the keys keep their names but not their contents: `position_survey` is now the tanks
	# READY to be surveyed, and `position_fix` the ones still waiting to come down. The names
	# stay because they are what the PWA's dashboard tiles already read.
	if "surveyPos" in menu:
		pending["position_survey"] = tank_survey.list_ready_to_survey(page_length=1)["total"]
	if "posFix" in menu:
		pending["position_fix"] = tank_survey.list_waiting_lowering(page_length=1)["total"]
	# Tanks nobody has ever located. Not "work" in the order sense — no document is waiting on
	# it — but it is the one number that says how blind the yard currently is, and it is the
	# thing the Letak Tank menu exists to drive to zero.
	if "tankPos" in menu:
		pending["unlocated"] = container_position.search_containers(
			page_length=1, only_unlocated=1
		)["total"]
	if pending:
		out["pending"] = pending

	# 4) Supervisor-only. "Every menu" is what SPV Lapangan means, so deriving it from
	# the menu keeps the role name out of the code — a second supervisor role added from
	# the UI gets this card too, with no deploy.
	if menu == set(MENU_KEYS):
		out["active_jobs"] = _count_active_job_containers(allowed)

	return out


@frappe.whitelist(methods=["GET"])
def activity_history(start=0, page_length=10, search=None, container=None):
	"""GET /api/v1/ess/activity-history — Container Activity timeline (Monitor "Riwayat").

	``container`` mempersempit ke satu tank: itu yang dibuka tombol "Lihat semua aktivitas"
	di kartu detail, dan feed penuhnya adalah endpoint yang sama tanpa parameter itu.
	"""
	require_menu("monitor")
	return container_activity.list_activity_history(
		start=start, page_length=page_length, search=search, container=container
	)


@frappe.whitelist(methods=["GET"])
def activity_detail(name=None):
	"""GET /api/v1/ess/activity-detail — one Container Activity record's full detail."""
	require_menu("monitor")
	return container_activity.get_activity_detail(name)
