import frappe

from container_depot.files import backfill
from container_depot.hooks import FILE_BEARING_DOCTYPES


def execute():
	"""Tempelkan foto PWA lama ke dokumennya supaya bukan cuma pengunggah yang bisa lihat.

	Semua foto yang naik dari PWA sebelum ini adalah File privat tanpa tuan: hanya pemiliknya
	yang boleh membukanya, rekannya dapat 403 (lihat container_depot/files.py). Hook penyimpanan
	menutup keran itu untuk yang baru; ini merapikan yang sudah terlanjur ada. Aman diulang.
	"""
	attached = backfill(FILE_BEARING_DOCTYPES)
	frappe.logger().info(f"attach_orphan_pwa_files: {attached} file ditempelkan")
