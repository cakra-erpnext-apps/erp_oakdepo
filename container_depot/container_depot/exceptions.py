"""Errors the PWA has to be able to tell apart.

Every refusal from a whitelisted endpoint reaches the handset as the same thing: HTTP 417
with a sentence of Indonesian in it. That is fine for a human reading a toast, and useless
for the offline queue, which has to decide what to DO with a refused row — and matching on
the text of a message somebody will reword next month is not a decision anyone should build
on.

Frappe puts the exception's class name into the JSON response as ``exc_type`` (see
``frappe/utils/response.py``), so a subclass is a contract the client can read. Subclassed
from ``ValidationError`` on purpose: the HTTP status, the Desk's handling and every existing
``assertRaises(frappe.ValidationError)`` keep working exactly as before.
"""

from __future__ import annotations

import frappe


class AlreadySettled(frappe.ValidationError):
	"""This document has already moved past the point the caller is asking for.

	The cleaning is signed off, the M&R is closed, the EIR is submitted. Raised for the case
	the offline queue meets after a day in a dead spot: the operator's work was queued, and
	by the time it left, somebody else had already finished the job on the Desk.

	It means "your request cannot land, and retrying will never change that" — as opposed to
	an ordinary ValidationError, which usually means "not like that, not yet". The queue
	shows the two differently: a settled row is a fact to be acknowledged and discarded, not
	a failure to be retried for ever. See ``frontend/src/data/outbox.js``.
	"""


class ClaimedByAnother(frappe.ValidationError):
	"""Pekerjaan ini sudah dipegang operator lain sejak dia menekan "Mulai".

	Bukan soal izin — di Desk semua orang yang berwenang tetap melihat dan membuka dokumen
	yang sama. Ini pagar lapangan: satu tangki tidak boleh dikerjakan (dan diisi checklist-nya)
	dua orang sekaligus, dan begitu diklaim harus jelas siapa yang memegangnya.

	Dipisahkan dari ``AlreadySettled`` karena artinya berbeda: dokumennya belum selesai, hanya
	bukan giliran pemanggil. PWA membacanya lewat ``exc_type`` untuk menampilkan toast dan
	memulangkan operator ke worklist — kasus paling sering: dia menekan notifikasi untuk
	order yang sudah diambil rekannya. Lihat ``container_depot.container_depot.work_claim``.
	"""
