"""Where each tank stands — recording it, reading it back, and finding the ones nobody knows.

Deliberately free of ``@frappe.whitelist`` so the exact same functions back both the ESS PWA
wrappers (``ess/container_position.py``) and any Desk / automation caller.

THE SHAPE OF THIS FEATURE
-------------------------
A tank's position is a fact about the TANK, not about a booking. It changes because a
reachstacker moved it, and the next person who needs it may be a surveyor, a washer, a
mechanic or the gate. So it is recorded on its own, by anyone, at any time::

    Container Position (one reading)  ->  Container.current_location
                                          Container.location_updated_on
                                          Container.location_updated_by

Everything else READS the master — the Survey Order screen above all, which shows each tank's
last known place next to when it was last checked. Nothing copies the location into its own
document, because a copy is frozen at the moment it was taken and starts lying on the first
correction.

The age travels with the answer everywhere, and that is not decoration. "Blok kanan, dicatat
2 jam lalu" is an instruction; "blok kanan, dicatat bulan Juni" is a guess. A screen that
shows only the place cannot tell an operator which one they are holding.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, date_diff, getdate, now_datetime, time_diff_in_seconds

from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_depots

DOCTYPE = "Container Position"

# How long a reading stays "fresh" on the screens, in hours. Not a rule the server enforces —
# nothing is refused for being stale — just the line the UI draws between an answer to act on
# and one to double-check. A shift is 8 hours; a position that survived a whole shift without
# anybody contradicting it is still the best thing anyone knows.
FRESH_HOURS = 12


def _coerce_photos(photos) -> list:
	"""Normalise the ``photos`` payload (JSON string or list of urls / {photo}) → url list."""
	if photos is None:
		return []
	if isinstance(photos, str):
		try:
			photos = json.loads(photos)
		except json.JSONDecodeError:
			frappe.throw(_("photos must be a JSON array."))
	if not isinstance(photos, list):
		frappe.throw(_("photos must be a list."))
	out = []
	for p in photos:
		url = (p.get("photo") if isinstance(p, dict) else p) or ""
		url = str(url).strip()
		if url:
			out.append(url)
	return out


def _attach_photos(rows) -> list:
	"""Hang each reading's photos off it, in ONE query for the whole page.

	Photos are the half of a position that cannot be argued with. "Blok kanan tumpukan 2" is
	somebody's description; the picture is what the next person matches against the stack in
	front of them, and it is what settles a tank reported in two places on the same morning.
	So every read that returns readings returns their pictures — a history of bare sentences
	makes the operator open each row to find out whether there is anything to look at.

	Row-by-row lookups are what make a long history feel slow on a handset, hence the single
	``in`` query and the grouping here.
	"""
	names = [r.get("name") for r in rows if r.get("name")]
	by_parent: dict = {}
	if names:
		for ph in frappe.get_all(
			"Container Position Photo",
			filters={"parent": ["in", names], "parenttype": DOCTYPE},
			fields=["parent", "photo"],
			order_by="idx asc",
		):
			if ph.photo:
				by_parent.setdefault(ph.parent, []).append(ph.photo)
	for r in rows:
		r["photos"] = by_parent.get(r.get("name"), [])
	return rows


def _guard_container_branch(container) -> None:
	"""Block reads/writes on a tank whose depot is outside the caller's branch."""
	assert_in_user_branch(depot=frappe.db.get_value("Container", container, "depot"))


def _age(recorded_on) -> dict:
	"""``{"hours": float|None, "fresh": bool}`` for a reading's timestamp.

	Returned rather than formatted: the phrasing ("2 jam lalu", "Sejak 09:12") is the
	screen's business, and two screens already want it two different ways.
	"""
	if not recorded_on:
		return {"hours": None, "fresh": False}
	hours = time_diff_in_seconds(now_datetime(), recorded_on) / 3600.0
	return {"hours": round(hours, 2), "fresh": hours <= FRESH_HOURS}


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
def record_position(container, location_note, notes=None, photos=None) -> dict:
	"""File one reading of where ``container`` is standing, and push it onto the master.

	Always an INSERT, never an update of the last one. A correction typed ten minutes later is
	a second reading, not a redaction of the first — the yard has to be able to see that a tank
	was reported in two places and when the story changed. The master keeps only the newest
	(``ContainerPosition.push_to_container``).

	Permissions are enforced (no bypass): every field role holds create on this doctype, which
	is the whole point — a wrong position costs whoever walks to the wrong stack next,
	whichever crew they are on.
	"""
	if not container:
		frappe.throw(_("Container wajib diisi."))
	_guard_container_branch(container)
	location_note = (str(location_note).strip() if location_note is not None else "")
	if not location_note:
		frappe.throw(_("Isi dulu letak container-nya."))

	doc = frappe.new_doc(DOCTYPE)
	doc.container = container
	doc.location_note = location_note
	doc.notes = notes
	doc.set("position_photos", [{"photo": url} for url in _coerce_photos(photos)])
	doc.insert()  # NOT ignore_permissions — DocPerm is the gate.

	return {
		"success": True,
		"name": doc.name,
		"container": container,
		"location_note": location_note,
		"recorded_on": str(doc.recorded_on),
		"recorded_by": doc.recorded_by,
		# Echoed back so a caller that is not about to re-fetch still knows what landed —
		# and so a `local:` ref that `send` swapped for a real URL is visibly resolved.
		"photos": [row.photo for row in doc.position_photos if row.photo],
	}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def get_container_position(container, history_length=5) -> dict:
	"""One tank's current location, how old it is, and the last few readings behind it.

	The history is what makes the current answer checkable: a tank reported in three different
	blocks this morning is a tank nobody has actually found, and no single "current location"
	can say that.
	"""
	if not container:
		frappe.throw(_("Container wajib diisi."))
	_guard_container_branch(container)
	tank = frappe.db.get_value(
		"Container", container,
		["name", "container_no", "depot", "status", "principal", "container_type", "size",
		 "eir_in_date",
		 "current_location", "location_updated_on", "location_updated_by", "target_lift_on",
		 "target_survey_on", "target_urgent_on"],
		as_dict=True,
	)
	if not tank:
		frappe.throw(_("Container {0} tidak ditemukan.").format(container))

	history = frappe.get_all(
		DOCTYPE,
		filters={"container": container},
		fields=["name", "location_note", "notes", "recorded_by", "recorded_on"],
		order_by="recorded_on desc, creation desc",
		limit_page_length=cint(history_length),
	)
	for h in history:
		h["recorded_on"] = str(h["recorded_on"]) if h["recorded_on"] else None
	_attach_photos(history)

	return {
		"container": tank.name,
		"container_no": tank.container_no,
		"depot": tank.depot,
		"principal": tank.principal,
		"container_type": tank.container_type,
		"status": tank.status,
		"target_lift_on": str(tank.target_lift_on) if tank.target_lift_on else None,
		"target_survey_on": str(tank.target_survey_on) if tank.target_survey_on else None,
		"target_urgent_on": str(tank.target_urgent_on) if tank.target_urgent_on else None,
		"location_note": tank.current_location,
		"location_updated_on": str(tank.location_updated_on) if tank.location_updated_on else None,
		"location_updated_by": tank.location_updated_by,
		# Never recorded at all is a different state from "recorded a long time ago", and the
		# screen says so differently ("Lokasi belum terdata" vs a stale badge).
		"located": bool(tank.current_location),
		**_age(tank.location_updated_on),
		"size": tank.size,
		# Berapa kali tank ini berpindah, dan sudah berapa lama ia di depo. Dua angka yang
		# mengubah cara membaca posisi terakhirnya: tank yang berpindah empat kali minggu ini
		# adalah tank yang catatannya cepat basi, sementara yang berdiri di tempat sama sejak
		# masuk sebulan lalu tidak perlu dicurigai walau catatannya tua.
		"moves": frappe.db.count(DOCTYPE, {"container": container}),
		"in_depot_days": (
			max(0, date_diff(now_datetime(), tank.eir_in_date)) if tank.eir_in_date else None
		),
		"history": history,
	}


# ---------------------------------------------------------------------------
# The queue — tanks whose place has to be known before their survey day
# ---------------------------------------------------------------------------
def _needs_position(tank, since) -> bool:
	"""The rule itself, on a row already loaded. ``since`` = creation of ``lift_on_booking``.

	True when nobody has ever recorded it, or when the last reading is OLDER THAN the booking
	that scheduled it. The second half is the whole point: a place written down in June is not
	a wrong answer, it is an answer to a question nobody was asking then — the tank has been
	moved by three reachstackers since, and the survey crew arriving on the day would be
	walking to a memory. Once anybody files a fresh reading the tank leaves the queue by
	itself, which is why the queue needs no document to close.

	Split out from :func:`needs_position` so the list below can apply the same rule to a whole
	page without asking the database once per tank — the bell rings for one container, the
	queue counts hundreds, and the two must not answer differently.
	"""
	if not tank or not tank.get("current_location"):
		return True
	if not tank.get("lift_on_booking"):
		return False
	return bool(since and tank.get("location_updated_on") and tank["location_updated_on"] < since)


def needs_position(container) -> bool:
	"""Does this tank still owe an answer about where it is? (one tank, by name)"""
	tank = frappe.db.get_value(
		"Container", container,
		["current_location", "location_updated_on", "lift_on_booking"],
		as_dict=True,
	)
	since = (
		frappe.db.get_value("Container Booking", tank.lift_on_booking, "creation")
		if tank and tank.lift_on_booking
		else None
	)
	return _needs_position(tank, since)


def open_position_orders(start=0, page_length=20) -> dict:
	"""The "cek letak tank" queue: tanks with a survey coming whose place is unknown or stale.

	Derived, not stored — see ``tank_survey._raise_position_orders`` for why there is no order
	document behind this. A tank qualifies when a live outbound booking has stamped a deadline
	on it (``lift_on_booking``) and :func:`needs_position` still says yes; filing one reading
	is what closes it.

	Ordered by the same rule as every other worklist (``worklist.priority_date``): survey day
	first, pickup day when no survey has been set. Branch-scoped like everything else here.
	"""
	from container_depot.container_depot.worklist import sort_by_priority

	filters = {"is_active": 1, "lift_on_booking": ["is", "set"]}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]

	rows = frappe.get_all(
		"Container",
		filters=filters,
		fields=["name", "container_no", "principal", "depot", "status", "target_lift_on",
				"target_survey_on", "target_urgent_on", "current_location", "location_updated_on",
				"location_updated_by", "lift_on_booking"],
		order_by="container_no asc",
		limit_page_length=0,
	)
	# Satu kueri untuk semua booking yang disebut halaman ini, bukan satu per tank: daftar ini
	# menyapu SETIAP container yang punya deadline, dan versi lamanya menembak dua query per
	# baris — beranda yang ikut menghitung antrean ini membayarnya di setiap kali dibuka.
	since = {}
	booking_names = list({r.lift_on_booking for r in rows if r.lift_on_booking})
	if booking_names:
		since = {
			b.name: b.creation
			for b in frappe.get_all(
				"Container Booking", filters={"name": ["in", booking_names]},
				fields=["name", "creation"], limit_page_length=0,
			)
		}
	rows = [r for r in rows if _needs_position(r, since.get(r.lift_on_booking))]
	total = len(rows)
	# `started` is never true here: there is no half-done state — a tank either has a fresh
	# reading (and has left this list) or it does not.
	rows = sort_by_priority(rows, lambda r: False, cint(start), cint(page_length))
	for it in rows:
		it["located"] = bool(it.get("current_location"))
		for k in ("target_lift_on", "target_survey_on", "target_urgent_on", "location_updated_on"):
			it[k] = str(it[k]) if it.get(k) else None
		it.update(_age(it.get("location_updated_on")))
	return {"items": rows, "total": total}


def search_containers(search=None, start=0, page_length=20, only_unlocated=0) -> dict:
	"""Tank finder: containers in the caller's branch, with their last known place.

	``search`` matches the container number (the only thing anyone standing in a yard has to
	hand). ``only_unlocated`` narrows to tanks nobody has ever recorded — the list to go and
	clear, and the reason the finder exists at all.

	Retired tanks are out: they are not in the yard to be found.

	ORDER — the tanks with a day against them come first, nearest day at the top. A yard has
	hundreds of tanks and only a handful are being waited for; those are the ones whose
	position somebody is about to walk on, so a list that opens on the stalest reading opens
	on the least urgent thing in the depot. The survey day wins over the pickup day, the same
	tie-break every other worklist uses (``worklist.priority_date``). Everything with no day
	at all keeps the old order underneath: never-recorded first, then stalest.

	Raw SQL because that ordering cannot be expressed through ``frappe.get_all`` — it refuses
	any function in ``order_by`` ("Invalid field format in Order By"), and ``target_survey_on
	asc`` alone would sort the NULLs (i.e. every tank nobody is waiting for) to the top, which
	is exactly backwards.
	"""
	where = ["c.is_active = 1"]
	args: dict = {}
	depots = get_user_depots()
	if depots is not None:  # restricted user: only their depots
		where.append("c.depot in %(depots)s")
		args["depots"] = tuple(depots or [""])
	if cint(only_unlocated):
		where.append("ifnull(c.current_location, '') = ''")
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		where.append("c.container_no like %(search)s")
		args["search"] = f"%{search}%"
	clause = " and ".join(where)

	# One expression, written once: the day this tank is wanted, or NULL when nobody is
	# waiting for it.
	due = "coalesce(c.target_survey_on, c.target_lift_on)"
	# An urgent tank comes first whatever its own two dates say — the same tier the Python
	# worklists apply (``worklist.sort_by_priority``), written again here because this list is
	# paged in SQL and never passes through them.
	urgent = "c.target_urgent_on"
	items = frappe.db.sql(
		f"""
		select c.name, c.container_no, c.principal, c.depot, c.status,
		       c.target_lift_on, c.target_survey_on, c.target_urgent_on, c.current_location,
		       c.location_updated_on, c.location_updated_by
		  from `tabContainer` c
		 where {clause}
		 order by ({urgent} is null) asc, {urgent} asc,
		          ({due} is null) asc, {due} asc, c.location_updated_on asc, c.container_no asc
		 limit %(page_length)s offset %(start)s
		""",
		{**args, "page_length": cint(page_length), "start": cint(start)},
		as_dict=True,
	)
	total = frappe.db.sql(
		f"select count(*) from `tabContainer` c where {clause}", args
	)[0][0]
	for it in items:
		it["located"] = bool(it.get("current_location"))
		it["target_lift_on"] = str(it["target_lift_on"]) if it.get("target_lift_on") else None
		it["target_survey_on"] = str(it["target_survey_on"]) if it.get("target_survey_on") else None
		it["target_urgent_on"] = str(it["target_urgent_on"]) if it.get("target_urgent_on") else None
		it.update(_age(it.get("location_updated_on")))
		it["location_updated_on"] = str(it["location_updated_on"]) if it.get("location_updated_on") else None
	return {"items": items, "total": total}


def list_position_history(container=None, start=0, page_length=20, search=None) -> dict:
	"""The readings feed — newest first, branch-scoped, optionally for one tank."""
	filters = {}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]  # restricted user: only their depots
	if container:
		filters["container"] = container
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		filters["container_no"] = ["like", f"%{search}%"]

	items = frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=["name", "container", "container_no", "depot", "location_note", "notes",
				"recorded_by", "recorded_on"],
		order_by="recorded_on desc, creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	for it in items:
		it["recorded_on"] = str(it["recorded_on"]) if it["recorded_on"] else None
	_attach_photos(items)
	return {"items": items, "total": frappe.db.count(DOCTYPE, filters)}


# ---------------------------------------------------------------------------
# Template posisi — daftar pendek di balik form, milik depot
# ---------------------------------------------------------------------------
TEMPLATE = "Container Position Template"

# Berapa hari ke belakang "sering diketik manual" melihat. Seminggu: cukup panjang untuk
# menangkap bay yang benar-benar dipakai berulang, cukup pendek supaya bay yang dipakai sekali
# waktu proyek bulan lalu tidak terus ditawarkan jadi template.
SUGGEST_DAYS = 7
# Berapa kali sebuah tulisan harus muncul sebelum ditawarkan. Dua sudah cukup: yang diketik
# dua kali dengan tangan adalah yang akan diketik ketiga kalinya.
SUGGEST_MIN = 2
# Setelah berapa hari sebuah posisi minta dicek ulang. Beda dari FRESH_HOURS di atas, dan
# memang dua pertanyaan yang berbeda: yang itu "boleh langsung dipakai?", yang ini "sudah
# waktunya ada yang berjalan ke sana dan melihat?".
RECHECK_DAYS = 7


def _one_depot(depot=None) -> str:
	"""Depot yang sedang dikelola template-nya, dan boleh dilihat pemanggil.

	Template adalah milik satu depot, jadi setiap layarnya harus tahu depot mana — sebuah
	daftar gabungan dari dua depot akan menawarkan bay yang tidak ada di yard tempat orangnya
	berdiri.
	"""
	allowed = get_user_depots()
	depot = (depot or "").strip()
	if depot and depot.lower() in ("undefined", "null", "none"):
		depot = ""
	if depot:
		if allowed is not None and depot not in allowed:
			frappe.throw(_("Depot {0} di luar cakupan branch Anda.").format(depot))
		return depot
	if allowed:
		return allowed[0]
	if allowed is None:
		first = frappe.get_all("Depot", filters={"is_active": 1}, order_by="name asc", limit=1)
		if first:
			return first[0].name
	frappe.throw(_("Belum ada depot yang bisa dikelola template-nya."))


def _usage(depot, labels_wanted) -> dict:
	"""``lower(label) -> {"used": n, "last": datetime}`` dari pencatatan nyata di depot itu.

	Dihitung dari Container Position, BUKAN dari kolom penghitung di template. Sebuah counter
	harus diperbarui setiap kali posisi dicatat, dihapus, atau template-nya diganti nama — dan
	begitu satu jalur lupa memperbaruinya, angkanya salah selamanya tanpa ada yang tahu. Di
	sini angkanya selalu jawaban atas data yang sebenarnya ada.
	"""
	if not labels_wanted:
		return {}
	rows = frappe.db.sql(
		"""
		select lower(trim(location_note)) as k, count(*) as used, max(recorded_on) as last
		  from `tabContainer Position`
		 where depot = %(depot)s and lower(trim(location_note)) in %(labels)s
		 group by lower(trim(location_note))
		""",
		{"depot": depot, "labels": tuple(labels_wanted)},
		as_dict=True,
	)
	return {r.k: {"used": r.used, "last": str(r.last) if r.last else None} for r in rows}


def list_templates(depot=None) -> dict:
	"""Template satu depot, urut tampil, plus tulisan yang sering diketik manual.

	Bagian kedua itu yang membuat daftar ini tidak menua: sebuah bay baru dibuka, semua orang
	mengetiknya dengan tangan, dan tidak ada yang merasa punya urusan membuka layar pengaturan
	untuk mendaftarkannya. Yang muncul di sini adalah tulisan yang sudah terbukti dipakai —
	tinggal diangkat jadi template dengan satu ketukan.
	"""
	depot = _one_depot(depot)
	rows = frappe.get_all(
		TEMPLATE,
		filters={"depot": depot},
		fields=["name", "label", "sort_order"],
		order_by="sort_order asc, creation asc",
		limit_page_length=0,
	)
	stats = _usage(depot, [r.label.strip().lower() for r in rows if r.label])
	items = []
	for r in rows:
		s = stats.get((r.label or "").strip().lower(), {})
		items.append({
			"name": r.name,
			"label": r.label,
			"sort_order": r.sort_order,
			"used": s.get("used", 0),
			"last_used": s.get("last"),
		})

	known = {(r.label or "").strip().lower() for r in rows}
	typed = frappe.db.sql(
		"""
		select trim(location_note) as label, count(*) as typed
		  from `tabContainer Position`
		 where depot = %(depot)s
		   and recorded_on >= %(since)s
		   and trim(ifnull(location_note, '')) != ''
		 group by lower(trim(location_note))
		having count(*) >= %(min)s
		 order by typed desc
		 limit 20
		""",
		{
			"depot": depot,
			"since": add_to_date(now_datetime(), days=-SUGGEST_DAYS),
			"min": SUGGEST_MIN,
		},
		as_dict=True,
	)
	return {
		"success": True,
		"depot": depot,
		"items": items,
		"suggestions": [
			{"label": t.label, "typed": t.typed}
			for t in typed
			if (t.label or "").strip().lower() not in known
		][:5],
	}


def add_template(depot=None, label=None) -> dict:
	"""Daftarkan satu posisi sebagai template depot. Baris baru selalu di URUTAN PALING BAWAH.

	Bukan paling atas: yang di atas adalah yang paling sering dipakai (diatur dengan digeser),
	dan sebuah template yang baru lahir belum pernah membuktikan apa pun.
	"""
	depot = _one_depot(depot)
	label = (label or "").strip()
	if not label:
		frappe.throw(_("Isi dulu posisinya."))
	last = frappe.db.sql(
		"""select max(sort_order) from `tabContainer Position Template` where depot = %s""", depot
	)
	doc = frappe.new_doc(TEMPLATE)
	doc.depot = depot
	doc.label = label
	doc.sort_order = cint((last or [[0]])[0][0]) + 1
	doc.insert()  # NOT ignore_permissions — DocPerm yang jadi gerbangnya.
	return {"success": True, "name": doc.name, "label": doc.label, "depot": depot}


def rename_template(name=None, label=None) -> dict:
	"""Ganti tulisan sebuah template.

	Posisi tank yang SUDAH tercatat dengan tulisan lama tidak ikut berubah — pencatatan
	menyimpan teksnya sendiri. Itu sengaja: mengubah daftar pilihan tidak boleh menulis ulang
	apa yang dilaporkan orang minggu lalu.
	"""
	doc = _template(name)
	doc.label = (label or "").strip()
	doc.save()
	return {"success": True, "name": doc.name, "label": doc.label}


def delete_template(name=None) -> dict:
	"""Buang sebuah template dari daftar pilihan depot. Pencatatan lama tidak tersentuh."""
	doc = _template(name)
	label, depot = doc.label, doc.depot
	doc.delete()
	return {"success": True, "label": label, "depot": depot}


def reorder_templates(names=None, depot=None) -> dict:
	"""Simpan urutan tampil, sesuai urutan ``names``.

	Yang dikirim adalah SELURUH daftar, bukan "pindahkan yang ini ke posisi tiga": dua orang
	yang menggeser bersamaan lewat perintah relatif bisa menghasilkan urutan yang tidak pernah
	dilihat keduanya, sementara daftar utuh cuma menghasilkan yang terakhir menang.
	"""
	depot = _one_depot(depot)
	if isinstance(names, str):
		try:
			names = json.loads(names)
		except json.JSONDecodeError:
			frappe.throw(_("names harus berupa array JSON."))
	if not isinstance(names, list):
		frappe.throw(_("names harus berupa array."))
	owned = set(frappe.get_all(TEMPLATE, filters={"depot": depot}, pluck="name"))
	for i, name in enumerate(names):
		if name not in owned:
			continue  # baris asing / sudah dihapus orang lain: dilewati, bukan meledak
		frappe.db.set_value(TEMPLATE, name, "sort_order", i, update_modified=False)
	return {"success": True, "depot": depot, "count": len(names)}


def template_usage(name=None) -> dict:
	"""Berapa tank yang SEKARANG berdiri di posisi ini — angka di dialog hapus.

	Bukan berapa kali template dipakai sepanjang masa: yang ditanya orang sebelum menghapus
	adalah "kalau daftar ini saya rapikan, ada berapa tank yang jadi susah dicari".
	"""
	doc = _template(name)
	count = frappe.db.sql(
		"""select count(*) from `tabContainer`
		    where is_active = 1 and depot = %(depot)s
		      and lower(trim(ifnull(current_location, ''))) = %(label)s""",
		{"depot": doc.depot, "label": (doc.label or "").strip().lower()},
	)
	return {
		"success": True,
		"name": doc.name,
		"label": doc.label,
		"depot": doc.depot,
		"tanks": cint((count or [[0]])[0][0]),
	}


def _template(name):
	"""Muat satu template, dengan penjaga branch — depot-nya harus boleh dilihat pemanggil."""
	if not name:
		frappe.throw(_("name wajib diisi."))
	doc = frappe.get_doc(TEMPLATE, name)
	assert_in_user_branch(depot=doc.depot)
	return doc


# ---------------------------------------------------------------------------
# Catat sekaligus — satu posisi, beberapa tank
# ---------------------------------------------------------------------------
def record_positions(containers=None, location_note=None, notes=None, photos=None) -> dict:
	"""Catat posisi yang SAMA untuk beberapa tank sekaligus.

	Tetap satu dokumen per tank, bukan satu dokumen berisi banyak tank: posisi adalah fakta
	tentang satu tank, dan tank yang besok dipindah sendirian harus bisa dikoreksi sendirian
	tanpa menyeret dua temannya. Yang dihemat layar ini adalah ketikannya, bukan catatannya.

	Foto yang sama menempel ke semuanya — satu jepretan tumpukan memang menjelaskan ketiganya.

    Gagal di tengah TIDAK dibatalkan seluruhnya: yang sudah tercatat tetap tercatat dan yang
    gagal dilaporkan per tank. Sebuah rollback di sini akan membuang pencatatan yang benar
    hanya karena tank keempat sudah keluar depo — dan operatornya sudah berjalan pergi.
	"""
	if isinstance(containers, str):
		try:
			containers = json.loads(containers)
		except json.JSONDecodeError:
			frappe.throw(_("containers harus berupa array JSON."))
	containers = [c for c in (containers or []) if c]
	if not containers:
		frappe.throw(_("Pilih dulu tank-nya."))
	if len(containers) > 50:
		frappe.throw(_("Maksimal 50 tank sekali simpan."))

	saved, failed = [], []
	for container in dict.fromkeys(containers):  # urutan tetap, kembar dibuang
		try:
			saved.append(record_position(container, location_note, notes=notes, photos=photos))
		except Exception as e:
			frappe.clear_last_message()
			failed.append({"container": container, "error": str(e)})
	return {
		"success": bool(saved),
		"location_note": (location_note or "").strip(),
		"saved": saved,
		"failed": failed,
	}


# ---------------------------------------------------------------------------
# Papan Posisi Tank — apa yang harus dikerjakan hari ini
# ---------------------------------------------------------------------------
def position_board(limit=8, group=None) -> dict:
	"""Empat angka dan tiga daftar pendek: layar pembuka menu Posisi Tank.

	Yang dijawab layar ini bukan "di mana tank X" (itu pencarian) melainkan "apa yang belum
	beres soal posisi di depo ini". Tiga daftarnya berurut menurut siapa yang paling merugikan
	kalau dibiarkan:

    * PERLU DICEK ULANG — ada jawabannya, tapi sudah tua. Ini yang paling berbahaya, karena ia
      terbaca seperti jawaban yang benar sampai seseorang berjalan ke sana.
    * BELUM TERDATA — tidak ada jawabannya sama sekali. Merepotkan, tapi jujur.
    * TERDATA HARI INI — bukan pekerjaan, melainkan bukti bahwa layar ini dipakai; tanpa ini
      operator yang sudah membereskan lima tank melihat layar yang tampak sama saja.

	Hanya tank yang sedang BERADA di depo. Tank yang sudah keluar tidak punya posisi untuk
	dicari, dan menghitungnya cuma membuat angka "belum terdata" tidak pernah bisa nol.

	``group`` = satu angka di puncak layar ditekan: yang dikembalikan hanya daftar itu, dan
	utuh — bukan potongan delapan baris. Angka di pil berjanji "sekian tank", dan pil yang
	menampilkan delapan setelah menjanjikan dua puluh tujuh adalah pil yang berbohong.
	"""
	limit = cint(limit) or 8
	group = (group or "").strip().lower()
	if group in ("", "all", "undefined", "null", "none"):
		group = None
	elif group not in ("located", "missing", "recheck"):
		frappe.throw(_("Filter tidak dikenal: {0}").format(group))
	# Sebuah daftar penuh tetap dibatasi. Depo dengan seribu tank tanpa posisi adalah masalah
	# yang tidak selesai dengan menggulir seribu baris di HP, dan tiga ratus sudah lebih
	# panjang dari yang akan dibaca siapa pun dalam satu shift.
	page = 300 if group else limit
	where = ["c.is_active = 1", "c.status in ('In_Depot', 'Available')"]
	args = {}
	depots = get_user_depots()
	if depots is not None:
		where.append("c.depot in %(depots)s")
		args["depots"] = tuple(depots or [""])
	clause = " and ".join(where)

	rows = frappe.db.sql(
		f"""
		select c.name, c.container_no, c.principal, c.depot, c.status, c.current_location,
		       c.location_updated_on, c.location_updated_by, c.eir_in_date
		  from `tabContainer` c
		 where {clause}
		""",
		args,
		as_dict=True,
	)

	stale_before = add_to_date(now_datetime(), days=-RECHECK_DAYS)
	today_start = getdate()
	recheck, missing, today_rows, located = [], [], [], []
	for r in rows:
		r["location_updated_on"] = str(r.location_updated_on) if r.location_updated_on else None
		r["eir_in_date"] = str(r.eir_in_date) if r.eir_in_date else None
		if not (r.current_location or "").strip():
			missing.append(r)
			continue
		located.append(r)
		recorded = r["location_updated_on"]
		if recorded and getdate(recorded) >= today_start:
			today_rows.append(r)
		if recorded and recorded < str(stale_before):
			recheck.append(r)

	# Yang paling tua duluan di daftar "perlu dicek": itu yang paling mungkin sudah bohong.
	recheck.sort(key=lambda r: r["location_updated_on"] or "")
	# Yang paling lama di depo duluan di daftar "belum terdata": tank yang baru masuk sepuluh
	# menit lalu memang belum sempat dicatat, yang masuk tiga hari lalu terlewat.
	missing.sort(key=lambda r: r["eir_in_date"] or "9999")
	today_rows.sort(key=lambda r: r["location_updated_on"] or "", reverse=True)
	# Daftar "terdata" dibuka dari yang PALING BASI, bukan yang terbaru: yang baru dicatat tidak
	# butuh dilihat siapa pun, dan daftar yang dibuka pada bacaan tersegar membuka pada baris
	# yang paling tidak berguna.
	located.sort(key=lambda r: r["location_updated_on"] or "")

	counts = {
		"all": len(rows),
		"located": len(located),
		"missing": len(missing),
		"recheck": len(recheck),
	}
	return {
		"success": True,
		"counts": counts,
		"group": group,
		# Satu pil ditekan = hanya daftar itu yang dikirim, utuh. Tanpa filter, ketiganya
		# dikirim sebagai potongan pendek karena layar pembuka menjawab "apa yang perlu
		# dikerjakan", bukan "sebutkan semuanya".
		"recheck": recheck[:page] if group in (None, "recheck") else [],
		"missing": missing[:page] if group in (None, "missing") else [],
		"today": today_rows[:limit] if group is None else [],
		"located": located[:page] if group == "located" else [],
		"recheck_days": RECHECK_DAYS,
	}
