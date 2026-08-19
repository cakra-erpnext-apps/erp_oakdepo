import frappe
from frappe.utils import getdate


def execute():
	"""Ganti kode EIR acak (EIR-91194AC3) dengan seri berurutan per tipe & tahun.

	Kode lama potongan md5 — tidak terbaca dan tidak terurut. Penomoran ulang mengikuti
	urutan ``creation`` supaya nomor kecil = EIR lama, dan counter ``tabSeries`` ikut
	digeser agar EIR berikutnya menyambung, bukan menabrak nomor yang sudah dipakai.
	Deterministik: dijalankan ulang menghasilkan nomor yang sama persis.

	Sekalian menulis ulang ``title`` — header form & kolom pertama list sekarang nomor
	container saja, bukan "<kode EIR> / <no container>" seperti v0_60.
	"""
	rows = frappe.db.sql(
		"""select name, inspection_type, creation from `tabInspection` order by creation asc""",
		as_dict=True,
	)
	counters = {}
	for row in rows:
		prefix = "EIR-OUT" if row.inspection_type == "EIR-Out" else "EIR-IN"
		key = f"{prefix}-{getdate(row.creation).year}-"
		counters[key] = counters.get(key, 0) + 1
		frappe.db.set_value(
			"Inspection", row.name, "inspection_id", f"{key}{counters[key]:05d}", update_modified=False
		)

	for key, current in counters.items():
		existing = frappe.db.sql("select current from `tabSeries` where name = %s", key)
		if existing:
			if existing[0][0] < current:
				frappe.db.sql("update `tabSeries` set current = %s where name = %s", (current, key))
		else:
			frappe.db.sql("insert into `tabSeries` (name, current) values (%s, %s)", (key, current))

	if frappe.db.has_column("Inspection", "title"):
		frappe.db.sql("update `tabInspection` set title = container_no")
