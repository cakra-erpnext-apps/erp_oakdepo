"""Foto PWA ikut dokumennya, bukan cuma milik yang mengunggah.

Frappe menilai izin baca sebuah File privat begini (``frappe/core/doctype/file/file.py``
``has_permission``): pemiliknya boleh, lalu — kalau file itu MENEMPEL pada sebuah dokumen —
siapa pun yang boleh membaca dokumen itu juga boleh. File privat yang tidak menempel ke mana
pun hanya bisa dibuka oleh yang mengunggahnya; orang lain dapat 403.

PWA mengunggah lewat ``/api/method/upload_file`` tanpa ``doctype``/``docname``: fotonya
diambil saat dokumennya belum tentu ada (foto duluan, draft menyusul; malah bisa nyangkut
offline dan baru naik belakangan). Jadi setiap foto lapangan lahir sebagai file yatim —
petugas yang memotret melihatnya, rekannya melihat gambar rusak.

Maka penempelan dikerjakan di sisi dokumen: begitu dokumen disimpan, setiap URL file yang
dirujuknya ditempelkan ke dokumen itu. Keputusan "siapa boleh lihat" pindah ke dokumennya —
yang boleh membuka EIR-nya, boleh melihat fotonya. Berlaku juga untuk tanda tangan dan
lampiran, dan tidak peduli lewat jalur mana file itu naik.
"""

import frappe

FILE_PREFIXES = ("/files/", "/private/files/")


def _file_urls(doc) -> set:
	"""Setiap URL file yang dirujuk dokumen ini — termasuk baris tabel anaknya."""
	urls = set()

	def walk(row):
		for value in row.values():
			if isinstance(value, str):
				if value.startswith(FILE_PREFIXES):
					urls.add(value)
			elif isinstance(value, list):
				for child in value:
					if isinstance(child, dict):
						walk(child)

	walk(doc.as_dict())
	return urls


def attach_to_document(doc, event=None):
	"""Tempelkan file yatim yang dirujuk dokumen ini ke dokumen ini (hook on_update)."""
	urls = _file_urls(doc)
	if not urls:
		return
	orphans = frappe.get_all(
		"File",
		filters={"file_url": ["in", sorted(urls)], "attached_to_doctype": ["is", "not set"]},
		pluck="name",
	)
	for name in orphans:
		# Sengaja db.set_value: menempelkan file bukan perubahan yang perlu tercatat sebagai
		# edit dokumen File, dan File.validate akan menuntut izin tulis atas dokumen tujuan —
		# padahal ini justru dijalankan DARI penyimpanan dokumen itu.
		frappe.db.set_value(
			"File",
			name,
			{"attached_to_doctype": doc.doctype, "attached_to_name": doc.name},
			update_modified=False,
		)


def _attach_columns(doctype: str):
	"""(tabel, kolom, kolom_nama_dokumen) untuk tiap field Attach di doctype + tabel anaknya."""
	meta = frappe.get_meta(doctype)
	for df in meta.fields:
		if df.fieldtype in ("Attach", "Attach Image"):
			yield f"tab{doctype}", df.fieldname, "name"
		elif df.fieldtype == "Table" and df.options:
			child = frappe.get_meta(df.options)
			for cdf in child.fields:
				if cdf.fieldtype in ("Attach", "Attach Image"):
					yield f"tab{df.options}", cdf.fieldname, "parent"


def backfill(doctypes) -> int:
	"""Tempelkan file yatim yang sudah terlanjur ada. Aman diulang; mengembalikan jumlahnya."""
	attached = 0
	for doctype in doctypes:
		if not frappe.db.exists("DocType", doctype):
			continue
		for table, column, owner_column in _attach_columns(doctype):
			scope = " AND parenttype = %(dt)s" if owner_column == "parent" else ""
			rows = frappe.db.sql(
				f"""SELECT DISTINCT `{owner_column}` AS docname, `{column}` AS file_url
				    FROM `{table}`
				    WHERE (`{column}` LIKE '/files/%%' OR `{column}` LIKE '/private/files/%%'){scope}""",
				{"dt": doctype},
				as_dict=True,
			)
			for row in rows:
				orphans = frappe.get_all(
					"File",
					filters={"file_url": row.file_url, "attached_to_doctype": ["is", "not set"]},
					pluck="name",
				)
				for name in orphans:
					frappe.db.set_value(
						"File",
						name,
						{"attached_to_doctype": doctype, "attached_to_name": row.docname},
						update_modified=False,
					)
				attached += len(orphans)
	return attached
