"""Controller halaman /login versi OAK.

Template www/login.html di app ini menang atas milik Frappe (TemplatePage
menelusuri app secara terbalik), dan controller dicari di folder yang sama —
tanpa file ini context login tidak pernah terisi. Seluruh logikanya memang
milik Frappe, jadi cukup dipakai ulang; yang ditambah hanya full_width supaya
templates/web.html tidak membungkus layout split di dalam .container.
"""

from frappe.www.login import get_context as _frappe_get_context

no_cache = True

APP_NAME = "Depot OAK"


def get_context(context):
	context = _frappe_get_context(context) or context
	context.full_width = True
	# Judul kartu ikut nama app ini, bukan "Frappe". Ditaruh di kode, bukan di
	# Website Settings, supaya tiap site baru langsung benar tanpa setelan manual.
	context.app_name = APP_NAME
	return context
