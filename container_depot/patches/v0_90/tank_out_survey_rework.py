"""Alur Tank Out dirombak: jadwal survey, alur dibalik, dan letak tank jadi milik tank.

APA YANG BERUBAH
----------------
Tiga hal sekaligus, dan ketiganya saling mengunci:

1. **Survey Order** — jadwal survey lapangan per booking Tank Out, dibuat dari ``survey_date``
   booking. Semua status hidup di sini, di baris ``Survey Order Tank`` per tank::

       Waiting Lowering --(Kalmar/Surveyor)--> Lowered --(Surveyor)--> Survey Done

   Dulu urutannya terbalik (surveyor dulu, Kalmar mengonfirmasi belakangan). Di lapangan itu
   tidak mungkin: tank yang masih ditumpuk tiga tingkat tidak bisa diperiksa sama sekali, jadi
   yang lebih dulu harus lowering-nya.

2. **Container Position** — bekas ``Container Position Survey``, sekarang jadi catatan letak
   tank yang berdiri sendiri: siapa saja di lapangan boleh menambah pembacaan baru, kapan saja,
   tanpa ada hubungannya dengan booking mana pun. Pembacaan terbaru dicerminkan ke master
   ``Container`` (``current_location`` / ``location_updated_on`` / ``location_updated_by``), dan
   Survey Order tinggal MEMBACA dari situ berikut tanggalnya. Tidak ada satu pun dokumen yang
   menyimpan salinan letak — salinan itu beku, dan mulai berbohong pada koreksi pertama.

3. **EIR-Out pindah tempat lahir** — dulu dibuat saat bon muat (Order Muat) disubmit, sekarang
   terbit saat survey tank ditutup. Bon tidak lagi membuatnya; ia menautkan diri ke draft yang
   sudah ada (``eir.attach_order_muat_to_eirs``) dan menstempel truk/sopir/shipper ke situ.
   Submit EIR-Out ditahan sampai bon terbit (``Inspection.before_submit``).

PEMETAAN DATA LAMA
------------------
``Container Position Survey`` dipecah dua, karena satu dokumen lama memang membawa dua hal yang
berbeda umurnya:

* **letaknya** (``location_note`` + foto) → tetap di dokumen yang sama, yang di-rename jadi
  ``Container Position``. Ini fakta tentang TANK dan tetap berlaku setelah booking-nya lewat.
* **status + stempelnya** → pindah jadi baris ``Survey Order Tank`` di bawah jadwal booking-nya.
  Ini fakta tentang satu PICKUP; satu tank yang diambil dua kali punya dua-duanya.

Status lama dipetakan begini (dua nama per baris karena site dev sempat menjalankan versi patch
ini yang lebih awal; keduanya diterima):

======================  ==================  ==========================================
Lama                    Baru                Kenapa
======================  ==================  ==========================================
Pending Survey          Waiting Lowering    Belum ada yang menyentuh.
In Survey               Waiting Lowering    Dipegang surveyor, tapi tank belum turun.
Surveyed / Lowered      Waiting Lowering    Letak tercatat (dipertahankan di master), tapi
                                            tank BELUM turun — langkah pertama yang dulu
                                            tidak ada, jadi antreannya balik ke Kalmar.
In Fix                  Waiting Lowering    Sama; Kalmar memang sedang menurunkannya.
Confirmed / Survey Done Survey Done         Kedua langkah sudah dijalani orang.
Cancelled               Cancelled           —
======================  ==================  ==========================================

Doctype lama TIDAK di-DROP, ia di-RENAME — datanya (letak + foto) masih dipakai, dan
me-rename-nya menjaga baris foto anaknya tetap menempel. Kolom yang tidak lagi punya arti di
dokumen letak (status, stempel lowering/survey, link booking) sengaja ditinggal, tidak di-DROP:
Frappe membiarkan kolom yatim sampai ``bench trim-database``, dan menjatuhkannya di sini berarti
membuang satu-satunya salinan data yang baru saja dipakai memindahkan status.

Idempoten: setiap langkah memeriksa dulu keadaan sasarannya.
"""

from __future__ import annotations

import frappe

OLD = "Container Position Survey"
OLD_PHOTO = "Container Position Survey Photo"
NEW = "Container Position"
NEW_PHOTO = "Container Position Photo"
SCHEDULE = "Survey Order"
ROW = "Survey Order Tank"

# Status lama -> status baru di baris tank. Semua yang setengah jalan pulang ke antrean Kalmar.
STATUS_MAP = {
	"Pending Survey": "Waiting Lowering",
	"In Survey": "Waiting Lowering",
	"Surveyed": "Waiting Lowering",
	"In Fix": "Waiting Lowering",
	"Lowered": "Waiting Lowering",
	"Confirmed": "Survey Done",
	"Survey Done": "Survey Done",
	"Cancelled": "Cancelled",
}

# Custom DocPerm yang harus DITIMPA, bukan ditambah. ``install.setup_permissions`` add-only
# (sengaja: admin boleh menyetel izin tanpa ditimpa tiap migrate), jadi di site yang sudah hidup
# baris lama akan bertahan selamanya dan fitur ini mati tanpa langkah ini.
SURVEY_PERMS = {
	"Team Kalmar": {"read": 1, "write": 1, "create": 0, "submit": 0, "cancel": 0, "amend": 0},
	"Team Survey": {"read": 1, "write": 1, "create": 0, "submit": 1, "cancel": 0, "amend": 0},
}

# Rule notifikasi yang penerimanya bertukar begitu alurnya dibalik.
ROLE_SWAP = {
	"position_survey_pending": ("Team Survey", "Team Kalmar"),
	"position_surveyed": ("Team Kalmar", "Team Survey"),
}

# Kartu lama yang sudah tidak punya doctype/status-nya lagi. Seeder kartu juga add-only.
STALE_NUMBER_CARDS = ["Survey Posisi Pending", "Tank Menunggu Lowering", "Tank Siap Disurvey"]


def execute():
	_rename_doctypes()
	_backfill_container_location()
	_move_status_to_survey_orders()
	_swap_survey_permissions()
	_drop_stale_number_cards()
	_link_existing_eir_out()
	_swap_notification_roles()


def _rename_doctypes() -> None:
	"""Pindahkan isi ``Container Position Survey`` ke ``Container Position`` (induk + fotonya).

	**Kenapa menyalin, bukan ``rename_doc``.** ``bench migrate`` menyinkronkan doctype SEBELUM
	menjalankan patch, dan di disk yang ada sekarang cuma folder yang baru — jadi begitu patch
	ini jalan, ``Container Position`` SUDAH dibuat sinkronisasi sebagai tabel kosong, dan
	rename akan menabraknya. Yang tersisa kemudian dibuang ``Removing orphan doctypes`` di akhir
	migrate, jadi kalau isinya tidak dipindah di sini, catatan letak lama hilang tanpa suara.

	Kolom disalin lewat IRISAN nama kolom kedua tabel: yang cuma ada di dokumen lama (status,
	stempel lowering/survey, link booking) memang bukan urusan dokumen letak, dan yang cuma ada
	di yang baru diisi langkah berikutnya. ``docstatus`` dipaksa 0 — dokumen lama submittable,
	yang baru tidak, dan baris docstatus 1 di doctype non-submittable tidak bisa dibuka di Desk.

	``rename_doc`` tetap dipakai kalau ternyata yang baru belum ada (site yang di-patch di luar
	urutan migrate biasa) — di situ ia jelas lebih murah daripada menyalin.
	"""
	from frappe.model.rename_doc import rename_doc

	for old, new in ((OLD_PHOTO, NEW_PHOTO), (OLD, NEW)):
		if not frappe.db.exists("DocType", old):
			continue
		if not frappe.db.exists("DocType", new):
			rename_doc("DocType", old, new, force=True, ignore_permissions=True)
			continue
		_copy_rows(old, new)
		frappe.delete_doc("DocType", old, force=True, ignore_permissions=True)
		if frappe.db.table_exists(old):
			frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{old}`")

	# Baris anak menyimpan nama doctype induknya sendiri; tidak ada langkah di atas yang
	# menyentuhnya, jadi tanpa ini fotonya menggantung pada induk yang tidak ada lagi.
	if frappe.db.table_exists(NEW_PHOTO):
		frappe.db.sql(
			f"UPDATE `tab{NEW_PHOTO}` SET parenttype = %s WHERE parenttype = %s", (NEW, OLD)
		)


def _columns_of(table: str) -> set:
	return {
		c.get("Field") or c.get("column_name")
		for c in frappe.db.sql(f"DESCRIBE `tab{table}`", as_dict=True)
	}


def _copy_rows(old: str, new: str) -> None:
	"""Salin baris ``old`` -> ``new`` pada kolom yang sama-sama dimiliki. Idempoten by ``name``."""
	if not (frappe.db.table_exists(old) and frappe.db.table_exists(new)):
		return
	shared = sorted(_columns_of(old) & _columns_of(new))
	if "name" not in shared:
		return
	cols = ", ".join(f"`{c}`" for c in shared)
	# docstatus dipaksa 0: lihat docstring _rename_doctypes.
	select = ", ".join("0" if c == "docstatus" else f"o.`{c}`" for c in shared)
	frappe.db.sql(
		f"""
		INSERT INTO `tab{new}` ({cols})
		SELECT {select} FROM `tab{old}` o
		 WHERE NOT EXISTS (SELECT 1 FROM `tab{new}` n WHERE n.name = o.name)
		"""
	)


def _backfill_container_location() -> None:
	"""Isi letak master Container dari pembacaan terakhir tiap tank.

	Dijalankan sebelum status dipindah, supaya jadwal yang dibuat langkah berikutnya langsung
	punya letak untuk ditampilkan — dan supaya angka "Tank Belum Terdata Letaknya" jujur sejak
	migrate pertama, bukan menghitung tank yang datanya sebenarnya sudah ada.

	``recorded_by`` / ``recorded_on`` kosong di baris lama (dulu tidak ada kolomnya): dipakai
	``surveyed_on`` lalu ``creation`` sebagai gantinya, karena itulah saat catatan letaknya
	benar-benar ditulis.
	"""
	if not _ensure_columns(NEW, "recorded_by", "recorded_on"):
		return
	if _has_columns(NEW, "surveyed_on", "surveyed_by"):
		frappe.db.sql(
			f"""
			UPDATE `tab{NEW}`
			   SET recorded_on = COALESCE(recorded_on, surveyed_on, creation),
			       recorded_by = COALESCE(recorded_by, surveyed_by, owner)
			"""
		)
	else:
		frappe.db.sql(
			f"""
			UPDATE `tab{NEW}`
			   SET recorded_on = COALESCE(recorded_on, creation),
			       recorded_by = COALESCE(recorded_by, owner)
			"""
		)

	rows = frappe.db.sql(
		f"""
		SELECT p.container, p.location_note, p.recorded_on, p.recorded_by
		  FROM `tab{NEW}` p
		  JOIN (SELECT container, MAX(recorded_on) AS newest
		          FROM `tab{NEW}`
		         WHERE location_note IS NOT NULL AND location_note != ''
		         GROUP BY container) newest
		    ON newest.container = p.container AND newest.newest = p.recorded_on
		 WHERE p.location_note IS NOT NULL AND p.location_note != ''
		""",
		as_dict=True,
	)
	seen = set()
	for r in rows:
		# Dua pembacaan pada detik yang sama: yang mana pun sama benarnya, ambil yang pertama.
		if not r.container or r.container in seen or not frappe.db.exists("Container", r.container):
			continue
		seen.add(r.container)
		frappe.db.set_value(
			"Container", r.container,
			{
				"current_location": r.location_note,
				"location_updated_on": r.recorded_on,
				"location_updated_by": r.recorded_by,
			},
			update_modified=False,
		)


def _move_status_to_survey_orders() -> None:
	"""Bikin Survey Order + baris tank dari survey lama yang masih menempel pada booking.

	Lewat provisioner yang sama dengan yang dipakai penyimpanan booking, bukan INSERT manual:
	satu definisi "jadwal yang benar" jauh lebih murah dirawat daripada dua, dan provisioner itu
	memang idempoten. Status per tank baru ditimpa SESUDAHNYA, karena provisioner selalu memulai
	tank dari ``Waiting Lowering`` dan survei yang sudah selesai tidak boleh mundur.

	Hanya survey yang punya ``booking``. Yang tanpa booking tidak pernah punya jadwal, dan
	letaknya sudah aman di master lewat langkah sebelumnya.
	"""
	if not _has_columns(NEW, "booking", "status"):
		return
	from container_depot.container_depot.doctype.survey_order.survey_order import refresh_progress
	from container_depot.container_depot.tank_survey import provision_survey_order_for_booking

	surveys = frappe.db.sql(
		f"""
		SELECT name, container, booking, status FROM `tab{NEW}`
		 WHERE booking IS NOT NULL AND booking != ''
		""",
		as_dict=True,
	)
	for booking in {s.booking for s in surveys}:
		if not frappe.db.exists("Container Booking", booking):
			continue
		try:
			provision_survey_order_for_booking(booking)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"backfill survey order for {booking}")

	carry = [c for c in ("surveyed_by", "surveyed_on") if _has_columns(NEW, c)]
	for s in surveys:
		new_status = STATUS_MAP.get(s.status)
		if not new_status or new_status == "Waiting Lowering":
			continue  # already where the provisioner left it
		order = frappe.db.get_value(SCHEDULE, {"booking": s.booking, "docstatus": ["!=", 2]}, "name")
		row = order and frappe.db.get_value(
			ROW, {"parent": order, "parenttype": SCHEDULE, "container": s.container}, "name"
		)
		if not row:
			continue
		values = {"status": new_status}
		# Stempel penyelesaian ikut pindah selama kolom lamanya masih ada, supaya "siapa yang
		# menutup survey ini" tidak hilang begitu saja.
		for col in carry:
			values[col] = frappe.db.get_value(NEW, s.name, col)
		frappe.db.set_value(ROW, row, values, update_modified=False)

	for order in frappe.get_all(SCHEDULE, pluck="name"):
		refresh_progress(order)


def _swap_survey_permissions() -> None:
	"""Tulis ulang Custom DocPerm Survey Order untuk Kalmar & Team Survey. Lihat SURVEY_PERMS."""
	for role, flags in SURVEY_PERMS.items():
		name = frappe.db.get_value("Custom DocPerm", {"parent": SCHEDULE, "role": role}, "name")
		if name:
			frappe.db.set_value("Custom DocPerm", name, flags, update_modified=False)
	frappe.clear_cache()


def _drop_stale_number_cards() -> None:
	"""Buang number card yang doctype atau statusnya sudah tidak ada — angkanya akan selamanya 0
	di sebelah kartu penggantinya."""
	for card in STALE_NUMBER_CARDS:
		if not frappe.db.exists("Number Card", card):
			continue
		frappe.db.delete("Workspace Number Card", {"number_card_name": card})
		frappe.delete_doc("Number Card", card, ignore_permissions=True, force=True)


def _link_existing_eir_out() -> None:
	"""Hubungkan draft EIR-Out yang sudah ada ke baris survey tank-nya yang sudah selesai.

	Draft ini lahir dari bon di alur lama. Membiarkannya tanpa tautan tidak merusak apa pun, tapi
	berarti ``provision_eir_out_for_survey`` tidak mengenali miliknya sendiri kalau surveynya
	nanti dibuka-lagi lalu ditutup lagi — dan itu persis kasus yang menerbitkan EIR kedua.
	"""
	if not _has_columns("Inspection", "survey_tank"):
		return
	for d in frappe.get_all(
		"Inspection",
		filters={"inspection_type": "EIR-Out", "docstatus": 0, "survey_tank": ["is", "not set"]},
		fields=["name", "container"],
	):
		row = frappe.db.get_value(
			ROW,
			{"container": d.container, "parenttype": SCHEDULE, "status": "Survey Done"},
			["name", "parent"],
			as_dict=True,
		)
		if row:
			frappe.db.set_value(
				"Inspection", d.name,
				{"survey_tank": row.name, "survey_order": row.parent},
				update_modified=False,
			)
			frappe.db.set_value(ROW, row.name, "eir_out", d.name, update_modified=False)


def _swap_notification_roles() -> None:
	"""Tukar penerima dua rule notifikasi yang antreannya bertukar tim.

	Hanya menyentuh baris peran yang persis disebut di :data:`ROLE_SWAP`. Peran lain di rule yang
	sama (SPV Lapangan, Admin Ops) dibiarkan — mereka mengawasi keduanya sejak awal, dan patch
	yang menulis ulang seluruh daftar akan membuang penyesuaian yang dibuat admin.
	"""
	for event_key, (drop, add) in ROLE_SWAP.items():
		rule = frappe.db.get_value("Depot Notification Rule", {"event_key": event_key}, "name")
		if not rule:
			continue
		try:
			doc = frappe.get_doc("Depot Notification Rule", rule)
			if add not in {r.role for r in (doc.get("roles") or [])}:
				doc.append("roles", {"role": add})
			for row in list(doc.roles):
				if row.role == drop:
					doc.remove(row)
			doc.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"swap notification roles for {event_key}")


def _has_columns(doctype: str, *columns: str) -> bool:
	"""Apakah SEMUA kolom ini benar-benar ada di tabelnya.

	``bench migrate`` menjalankan patch sesudah sinkronisasi doctype, jadi kolom baru mestinya
	sudah ada — tapi patch yang mati di site yang sinkronisasinya gagal separuh hanya menambah
	satu kegagalan di atas kegagalan, dan langkah lain di file ini masih bisa jalan.
	"""
	if not frappe.db.table_exists(doctype):
		return False
	existing = {
		c.get("Field") or c.get("column_name")
		for c in frappe.db.sql(f"DESCRIBE `tab{doctype}`", as_dict=True)
	}
	return all(c in existing for c in columns)


def _ensure_columns(doctype: str, *columns: str) -> bool:
	"""Pastikan kolom baru sudah ada sebelum di-UPDATE; True kalau tabelnya siap dipakai.

	Rename doctype terjadi DI DALAM patch ini, sesudah sinkronisasi doctype migrate — jadi tabel
	bernama baru itu belum pernah dilihat sinkronisasi, dan kolom yang hanya ada di JSON baru
	belum tentu sudah dibuat. Satu ``updatedb`` menutup celah itu.
	"""
	if not frappe.db.table_exists(doctype):
		return False
	if _has_columns(doctype, *columns):
		return True
	frappe.reload_doctype(doctype, force=True)
	frappe.db.updatedb(doctype)
	return _has_columns(doctype, *columns)
