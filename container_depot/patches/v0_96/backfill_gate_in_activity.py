"""Tulis baris "Gate In" yang hilang di Container Activity untuk kedatangan lama.

Kedatangan lewat bon (Order Bongkar) tidak pernah menulis baris itu: Gate Entry-nya sengaja
ditinggal DRAFT — ``GateEntry.on_submit`` akan menolak tank yang barusan ditaruh di depo oleh
bon yang sama — sehingga ``on_submit``, satu-satunya penulis baris "Gate In", tidak pernah
jalan. Yang menulisnya cuma jalur kiosk SST (``api.register_gate_entry``), yang jarang
dipakai. Akibatnya setiap penghitung yang membaca tabel itu — kartu "Tank masuk" di Beranda
PWA, kartu hari ini di monitor Desk, dan umur tank di depo — menganggap depo tidak pernah
menerima tank.

Jalurnya sudah diperbaiki di ``Order Bongkar._record_gate_in``; ini merapikan yang telanjur
tercatat, dibangun dari Riwayat Gate itu sendiri: setiap Gate Entry yang punya
``gate_in_timestamp`` adalah satu kedatangan yang benar-benar terjadi. Waktunya diambil dari
stempel itu, bukan hari ini, supaya angka "hari ini" tidak tiba-tiba melonjak oleh kedatangan
bulan lalu.

Aman diulang: baris yang Gate Entry-nya sudah punya "Gate In" dilewati.
"""

import frappe

from container_depot.container_depot.container_activity import log_container_activity


def execute():
	frappe.reload_doc("container_depot", "doctype", "container_activity")
	entries = frappe.get_all(
		"Gate Entry",
		filters={"gate_in_timestamp": ["is", "set"], "status": ["!=", "Cancelled"]},
		fields=["name", "container_no", "gate_in_timestamp", "security_guard", "order_ref"],
	)
	logged = set(
		frappe.get_all(
			"Container Activity",
			filters={"activity_type": "Gate In", "reference_doctype": "Gate Entry"},
			pluck="reference_name",
		)
	)
	for ge in entries:
		if ge.name in logged:
			continue
		# Gate Entry menyimpan NOMOR tank, bukan link ke masternya.
		container = frappe.db.get_value("Container", {"container_no": ge.container_no})
		if not container:
			continue
		# Kedatangan yang sama bisa sudah tercatat tanpa menunjuk Gate Entry-nya (jalur lama).
		# Dicocokkan ke jamnya, bukan ke harinya: satu tank bisa masuk dua kali dalam sehari.
		if frappe.db.exists(
			"Container Activity",
			{"container": container, "activity_type": "Gate In", "activity_time": ge.gate_in_timestamp},
		):
			continue
		log_container_activity(
			container, "Gate In",
			reference_doctype="Gate Entry", reference_name=ge.name,
			performed_by=ge.security_guard,
			activity_time=ge.gate_in_timestamp,
			summary=f"Gate-in (Bon {ge.order_ref})" if ge.order_ref else "Gate-in",
		)
	frappe.db.commit()
