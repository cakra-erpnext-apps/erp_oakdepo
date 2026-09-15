"""Halaman bagikan APK Depot OAK — ``/depot-app``.

Ada supaya APK bisa dibagikan tanpa mengirim file lewat chat: satu link (atau satu
QR di dinding kantor) yang selalu menunjuk APK terbaru. Tombolnya dipasang di Desk
lewat shortcut Workspace "Download App".

Sengaja terbuka untuk Guest. Yang diunduh cuma shell TWA — tidak ada data depo di
dalamnya, dan isinya tetap dikunci sesi Frappe begitu app dibuka. Kalau halaman ini
minta login, orang baru justru tidak bisa memasang app-nya.

APK-nya TIDAK ikut repo. Admin meng-upload File publik berakhiran ``.apk`` (File
manager Desk), dan halaman ini memakai yang paling baru. Jadi rilis berikutnya
cukup upload ulang — tanpa deploy, tanpa field settings baru.
"""

import frappe
from frappe.utils import get_url

from container_depot.print_utils import qr_data_uri

no_cache = 1


def get_apk():
	"""File APK publik terbaru, atau ``None`` kalau belum ada yang di-upload."""
	rows = frappe.get_all(
		"File",
		filters={"is_private": 0, "file_name": ("like", "%.apk")},
		fields=["file_name", "file_url", "file_size", "creation"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def get_context(context):
	context.no_cache = 1
	context.apk = get_apk()
	context.page_url = get_url("/depot-app")
	context.qr = qr_data_uri(context.page_url)
	# Yang boleh meng-upload APK-nya juga yang perlu melihat instruksi upload.
	context.is_admin = "System Manager" in frappe.get_roles()
	return context
