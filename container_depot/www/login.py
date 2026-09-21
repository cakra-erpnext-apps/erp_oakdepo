"""Controller halaman /login versi OAK.

Template www/login.html di app ini menang atas milik Frappe (TemplatePage
menelusuri app secara terbalik), dan controller dicari di folder yang sama —
tanpa file ini context login tidak pernah terisi. Seluruh logikanya memang
milik Frappe, jadi cukup dipakai ulang; yang ditambah hanya full_width supaya
templates/web.html tidak membungkus layout split di dalam .container, plus
jalan keluar ``?switch=1`` (lihat :func:`get_context`).
"""

import frappe
from frappe.www.login import get_context as _frappe_get_context

no_cache = True

APP_NAME = "Depot OAK"


def get_context(context):
	"""Halaman login, dengan satu tambahan: ``/login?switch=1`` = ganti akun.

	Frappe melempar siapa pun yang sesinya masih hidup langsung masuk (frappe/www/login.py:
	``if frappe.session.user != "Guest": raise frappe.Redirect``), jadi form login TIDAK PERNAH
	tampil selama cookie ``sid`` lama masih sah — dan ``session_expiry`` bawaan mengukur itu
	dalam hari. Akibatnya orang yang membuka /login untuk masuk sebagai orang lain justru
	dilempar masuk sebagai pemilik sesi sebelumnya, tanpa satu pun layar yang bertanya.

	Itu bukan kasus pinggiran di sini: HP lapangan dioper antar shift, dan satu laptop dipakai
	menguji akun customer. Logout lewat Desk/PWA memang ada, tapi menuntut orang tahu bahwa
	mereka sedang salah akun — padahal gejalanya justru "kok saya jadi dia".

	Yang sengaja TIDAK dilakukan: mengubah perilaku /login biasa. Auto-redirect itu benar untuk
	pemakaian normal (buka /login dengan sesi hidup = tidak perlu mengetik ulang password).
	Cukup sediakan URL yang memutusnya.
	"""
	# Logout DULU, baru render: setelah ini sesi = Guest, jadi `_frappe_get_context` di bawah
	# tidak lagi punya alasan untuk redirect dan form-nya tampil.
	if frappe.session.user != "Guest" and frappe.form_dict.get("switch"):
		frappe.local.login_manager.logout()
		frappe.db.commit()  # nosemgrep — GET, tapi baris sesi harus benar-benar hilang

	context = _frappe_get_context(context) or context
	context.full_width = True
	# Judul kartu ikut nama app ini, bukan "Frappe". Ditaruh di kode, bukan di
	# Website Settings, supaya tiap site baru langsung benar tanpa setelan manual.
	context.app_name = APP_NAME
	return context
