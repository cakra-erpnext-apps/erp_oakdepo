"""Per-request language for the depot PWA (/depot).

The PWA lets each device pick Indonesian (default) or English and sends the choice as the
`X-Depot-Lang` header on every /api call (frontend/src/utils/lang.js). This hook turns it
into `frappe.local.lang`, so everything passed through `_()` answers in that language:

* ``id`` -> Frappe/ERPNext's own Indonesian catalogue, plus ``translations/id.csv`` for
  this app's English-source messages and master data (EIR checklist, damage / repair
  codes…), plus any Translation rows an admin adds in the Desk.
* ``en`` -> ``en-GB``, not ``en``: the Desk runs as ``en-US`` and inherits every ``en``
  translation, so an English pack filed under ``en`` would silently turn the Desk's
  Indonesian messages English too. ``en-GB`` is used by nobody here and is still a locale
  babel knows, so date formatting keeps working. Its pack is ``translations/en-GB.csv``
  (this app's Indonesian-source messages -> English).

No header (the Desk, API clients, an old cached PWA build) leaves Frappe's own choice alone.

The choice itself is stored per user as the user default ``depot_lang`` (no schema: Frappe's
DefaultValue table), so it follows the operator across handsets and so notifications —
written in someone else's request — can be phrased in each recipient's language
(notify.py).
"""

import frappe

PWA_LANGS = {"id": "id", "en": "en-GB"}
DEFAULT_KEY = "depot_lang"


def get_user_lang(user: str | None = None) -> str:
	"""The user's PWA language, ``id`` or ``en``. Indonesian unless they picked English."""
	return "en" if frappe.defaults.get_user_default(DEFAULT_KEY, user or frappe.session.user) == "en" else "id"


def frappe_langs_for(users) -> dict[str, str]:
	"""{user: frappe lang code} for a batch of recipients, in one query."""
	picked = dict(
		frappe.get_all(
			"DefaultValue",
			filters={"parent": ["in", list(users) or [""]], "defkey": DEFAULT_KEY},
			fields=["parent", "defvalue"],
			as_list=True,
		)
	)
	return {u: PWA_LANGS["en" if picked.get(u) == "en" else "id"] for u in users}


def set_pwa_language():
	lang = PWA_LANGS.get(frappe.get_request_header("X-Depot-Lang") or "")
	if lang:
		frappe.local.lang = lang
