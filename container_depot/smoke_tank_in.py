"""Smoke test alur CONTAINER MASUK (Tank In), dijalankan berurutan seperti aslinya.

Urutannya mengikuti apa yang benar-benar dikerjakan orang depot, satu langkah menurunkan
langkah berikutnya:

    seeder (masters) -> Depot Contract Active -> Container Booking
      -> bayar (Cash: Sales Invoice + Payment Entry / TOP: dilewati)
      -> booking submit -> Booking Code -> gate in
      -> [1] Order Bongkar  (submit -> EIR-In ter-provision otomatis)
      -> EIR-In Empty Dirty + kerusakan  (submit)
      -> [2] Cleaning Order (karena dirty) + [3] Repair Order (karena ada kerusakan)
      -> container siap di depot

Tiga order itu — Bongkar, Cleaning, Repair — semuanya turun dari booking yang sama dan
container yang sama; tidak ada container atau booking sampingan yang dibuat hanya untuk
menguji satu cabang.

MASTERS TIDAK PERNAH DIBUAT DI SINI. Script ini memakai data seeder apa adanya
(``container_depot.seed_dev``): company, branch, depot, item, Depot Service Menu, customer
dan Depot Contract. Yang dibuat hanya dokumen transaksi, semuanya ditandai ``SMOKE`` dan
dihapus lagi di akhir — termasuk kalau di tengah jalan gagal.

Jalankan (site dev):

    bench --site oakdepo.localhost execute container_depot.smoke_tank_in.run

    # simpan datanya untuk dilihat di PWA/Desk (ingat bersihkan lagi nanti)
    bench --site oakdepo.localhost execute container_depot.smoke_tank_in.run --kwargs "{'keep':1}"

    # sapu sisa run yang gagal di tengah
    bench --site oakdepo.localhost execute container_depot.smoke_tank_in.run --kwargs "{'cleanup_only':1}"

    # bayar pakai Bank Transfer, bukan Cash (lihat catatan di _pay_invoice)
    bench --site oakdepo.localhost execute container_depot.smoke_tank_in.run --kwargs "{'payment_mode':'Bank Transfer'}"

Dijalankan sebagai Administrator, jadi semua guard peran ESS terlewat; yang diuji di sini
alur dan datanya, bukan RBAC-nya.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import flt, now_datetime, today

# --- penanda data uji --------------------------------------------------------------
# Semua dokumen yang dibuat run ini bisa dilacak dari sini. Nomor container ISO wajib
# tepat 11 karakter.
CNO = "SMOKEIN0001"
DO_PREFIX = "DO-SMOKE-"

# Kondisi yang sengaja dipilih supaya SATU EIR menurunkan DUA follow-up sekaligus:
# Empty Dirty -> Cleaning Order, dan minimal satu baris kerusakan -> Repair Order.
TANK_CONDITION = "EMPTY DIRTY"


def _log(msg):
	print(msg)
	frappe.logger("smoke_tank_in").info(msg)


def _finance_enabled():
	from container_depot import finance

	return bool(finance.is_enabled())


def _set_finance(enabled):
	"""Nyalakan/matikan saklar invoicing, kembalikan nilai sebelumnya.

	Site ini boleh saja jalan operations-only (tanpa invoice sama sekali) — itu keputusan
	konfigurasi, bukan bug. Tapi alur Tank In yang lengkap butuh Sales Invoice + Payment
	Entry, jadi run ini menyalakannya sebentar dan MENGEMBALIKAN apa adanya di akhir.
	"""
	from container_depot import finance
	from frappe.utils import cint

	before = cint(frappe.db.get_single_value(finance.SETTINGS, "enable_finance", cache=False))
	want = 1 if enabled else 0
	if before == want:
		return before
	frappe.db.set_single_value(finance.SETTINGS, "enable_finance", want)
	frappe.db.commit()
	finance.clear_cache()
	return before


class Smoke:
	def __init__(self, keep=False, payment_mode="Cash"):
		self.keep = keep
		self.payment_mode = payment_mode
		self.passed = 0
		self.failed = []
		self.created = []  # (doctype, name) urut pembuatan

		# diisi ensure_masters()
		self.company = None
		self.contract = None
		self.customer = None
		self.price_list = None
		self.currency = None
		self.depot = None
		self.branch = None
		# diisi sepanjang alur
		self.booking = None
		self.sales_invoice = None
		self.payment_entry = None
		self.booking_code = None
		self.gate_entry = None
		self.order_bongkar = None
		self.eir = None
		self.cleaning_order = None
		self.repair_order = None

	# -- runner -------------------------------------------------------------
	def track(self, doctype, name):
		if name and (doctype, name) not in self.created:
			self.created.append((doctype, name))
		return name

	def step(self, label, fn, expect_error=False):
		"""Jalankan satu langkah. ``expect_error=True`` untuk langkah yang MEMANG harus ditolak."""
		try:
			result = fn()
			if expect_error:
				self.failed.append((label, "seharusnya ditolak, tapi lolos"))
				_log(f"[GAGAL] {label} — seharusnya ditolak, tapi lolos")
				return None
			self.passed += 1
			_log(f"[OK]    {label}")
			return result
		except Exception as e:
			msg = str(e).splitlines()[0][:160] if str(e) else e.__class__.__name__
			if expect_error:
				self.passed += 1
				_log(f"[OK]    {label} — ditolak seperti seharusnya ({msg})")
				return None
			self.failed.append((label, msg))
			_log(f"[GAGAL] {label} — {msg}")
			return None

	def check(self, label, ok, detail=""):
		if ok:
			self.passed += 1
			_log(f"[OK]    {label}")
		else:
			self.failed.append((label, detail))
			_log(f"[GAGAL] {label} — {detail}")
		return bool(ok)

	# =======================================================================
	# 0) SEEDER — dipakai apa adanya, hanya diperiksa
	# =======================================================================
	def ensure_masters(self):
		"""Pastikan data seeder ada. Tidak membuat apa pun — kalau kurang, run dihentikan."""
		from container_depot.container_depot import service_menu

		self.company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
		self.check("Seeder · Company ada", bool(self.company))

		# Depot + Branch dari seeder (OAK1/OAK2/OAKSBY).
		self.depot = frappe.db.get_value("Depot", {"is_active": 1}, "name")
		self.branch = frappe.db.get_value("Depot", self.depot, "branch") if self.depot else None
		self.check("Seeder · Depot aktif + Branch-nya ada", bool(self.depot and self.branch),
			f"depot={self.depot} branch={self.branch}")

		# Service Menu yang dipakai picker Cleaning / Maintenance.
		for menu in ("Cleaning", "Maintenance"):
			self.check(f"Seeder · Depot Service Menu '{menu}' aktif", service_menu.is_real_menu(menu))

		# Item LOLO yang jadi charge booking.
		self.check("Seeder · item 'Lift Off' ada", bool(frappe.db.exists("Item", "Lift Off")))

		# --- Depot Contract yang Active DAN punya customer -----------------
		# Inilah sumber semua harga di alur ini: price list-nya yang mengisi charge booking,
		# tarif cleaning, dan tarif M&R. Tanpa ini tidak ada yang bisa dibilling.
		row = frappe.db.get_value(
			"Depot Contract",
			{"status": "Active", "customer": ["is", "set"]},
			["name", "customer", "payment_type", "currency", "generated_price_list"],
			as_dict=True,
			order_by="valid_from desc",
		)
		if not self.check("Seeder · ada Depot Contract Active + customer", bool(row),
				"tidak ada kontrak Active — seed/buat kontrak dulu"):
			return False
		self.contract, self.customer = row.name, row.customer
		self.price_list, self.currency = row.generated_price_list, row.currency
		self.check("Kontrak · punya generated Price List", bool(self.price_list), f"contract={self.contract}")

		# Customer master-nya benar-benar ada (bukan link menggantung).
		self.check("Kontrak · customer master ada", bool(frappe.db.exists("Customer", self.customer)),
			f"customer={self.customer}")

		# Mode pembayaran yang boleh dipakai customer ini, dibaca dari kontraknya —
		# persis yang dibaca form booking.
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			customer_payment_modes,
		)
		self.modes = customer_payment_modes(self.customer)
		self.check("Kontrak · payment mode terbaca (Cash/TOP)", bool(self.modes), f"modes={self.modes}")

		_log(f"masters: company={self.company} depot={self.depot} branch={self.branch} "
			f"contract={self.contract} customer={self.customer} "
			f"price_list={self.price_list} {self.currency} modes={self.modes}")
		return True

	# =======================================================================
	# 1) CONTAINER BOOKING
	# =======================================================================
	def create_booking(self):
		"""Booking Tank In atas kontrak yang aktif tadi.

		``container_no`` sengaja dikirim tanpa link Container: untuk Tank In, controller
		yang membuat master container-nya sendiri (pre-arrival, status Booked) dan
		menempelkan principal = customer booking. Itu yang diperiksa setelahnya —
		"owner containernya sudah terbuat dan cocok".
		"""
		# Cash didahulukan supaya jalur invoice + Payment Entry ikut teruji; kalau
		# kontraknya TOP-only, alur pembayaran memang dilewati (postpaid).
		pay_type = "Cash" if "Cash" in (self.modes or []) else (self.modes or ["TOP"])[0]

		def _mk():
			doc = frappe.get_doc({
				"doctype": "Container Booking",
				"direction": "Tank In",
				"customer": self.customer,
				"principal": self.customer,
				"contract": self.contract,
				"depot": self.depot,
				"branch": self.branch,
				"payment_type": pay_type,
				"booking_status": "Draft",
				"do_reference": f"{DO_PREFIX}{self.tag}",
				# Charge = Lift Off, tarifnya diambil sendiri dari price list kontrak.
				"charges": [{"item": "Lift Off"}],
				"items": [{
					"container_no": CNO,
					"condition": TANK_CONDITION,
					"tanggal_bongkar": today(),
				}],
			}).insert(ignore_permissions=True)
			self.booking = doc.name
			self.track("Container Booking", doc.name)
			return doc

		doc = self.step("Booking · buat draft Tank In dari kontrak aktif", _mk)
		if not doc:
			return False

		self.payment_type = doc.payment_type
		self.check("Booking · payment type ikut kontrak", doc.payment_type in (self.modes or []),
			f"booking={doc.payment_type} kontrak={self.modes}")

		# Container master-nya: dibuat controller, principal harus = pemilik kontrak.
		line = doc.items[0]
		self.track("Container", line.container)
		owner = frappe.db.get_value("Container", line.container, ["principal", "status"], as_dict=True) or frappe._dict()
		self.check("Container · master terbuat dari booking (pre-arrival)",
			bool(line.container) and owner.status == "Booked",
			f"container={line.container} status={owner.status}")
		self.check("Container · owner/principal cocok dengan customer kontrak",
			owner.principal == self.customer, f"principal={owner.principal} customer={self.customer}")

		# Charge harus terharga dari price list kontrak, bukan 0.
		rate = flt(doc.charges[0].rate)
		self.check("Booking · charge terharga dari price list kontrak", rate > 0,
			f"rate={rate} price_list={self.price_list}")
		self.booking_total = flt(doc.charges_total) or rate
		return True

	# =======================================================================
	# 2) PEMBAYARAN — Cash: invoice + Payment Entry. TOP: dilewati.
	# =======================================================================
	def settle(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			generate_invoice,
		)

		if not _finance_enabled():
			# Tanpa saklar ini, app memang tidak menerbitkan invoice sama sekali —
			# jadi bukan alurnya yang salah, sitenya yang dikonfigurasi operations-only.
			self.check("Finance · saklar invoicing menyala", False,
				"Depot Finance Settings.enable_finance = 0 di site ini; jalur Cash dilewati")
			return False

		if self.payment_type != "Cash":
			# TOP itu postpaid: tidak ada invoice per booking, ditagih belakangan lewat
			# consolidated billing. Booking-nya langsung boleh disubmit.
			self.step("Booking TOP · tidak boleh dibuatkan invoice per-booking",
				lambda: generate_invoice(self.booking), expect_error=True)
			self.step("Booking TOP · submit langsung", self._submit_booking)
			return self.check("Booking TOP · submitted + Unpaid (akrual)",
				frappe.db.get_value("Container Booking", self.booking, "docstatus") == 1)

		# --- Cash: Draft -> Pending Payment + Sales Invoice ---------------
		res = self.step("Invoice · Generate Invoice (Draft → Pending Payment)",
			lambda: generate_invoice(self.booking))
		if not res:
			return False
		self.sales_invoice = res["sales_invoice"]
		self.track("Sales Invoice", self.sales_invoice)

		si = frappe.get_doc("Sales Invoice", self.sales_invoice)
		# Harga barangnya harus persis sama dengan Total Charges booking. Grand Total boleh
		# lebih besar: model billing depot menagih labour terpisah — manhour tiap baris
		# ditotal di header, dikali "Hour", lalu ditambahkan sebagai baris Actual "Manhour"
		# (lihat custom field di install.py). Jadi Net Total = harga, Grand Total = harga +
		# labour (+ pajak kalau template PPN dipasang).
		manhour = flt(si.get("manhour_amount"))
		self.check("Invoice · harga (Net Total) sama dengan Total Charges booking",
			flt(si.net_total) == flt(self.booking_total),
			f"net={si.net_total} booking={self.booking_total}")
		self.check("Invoice · Grand Total = Net Total + tambahan (labour/pajak)",
			flt(si.grand_total) == flt(si.net_total) + flt(si.total_taxes_and_charges),
			f"grand={si.grand_total} net={si.net_total} tambahan={si.total_taxes_and_charges}")
		self.check("Invoice · biaya manhour ikut ditagih terpisah",
			manhour <= 0 or flt(si.total_taxes_and_charges) >= manhour,
			f"manhour={manhour} tambahan={si.total_taxes_and_charges}")
		self.check("Invoice · mata uang ikut kontrak", si.currency == self.currency,
			f"invoice={si.currency} kontrak={self.currency}")

		# Gate menolak selama Cash belum lunas — dicek sebelum dibayar, bukan sesudah.
		self.step("Gate · ditolak selama Cash belum dibayar", self._gate_generate, expect_error=True)

		self.step("Invoice · submit", lambda: frappe.get_doc("Sales Invoice", self.sales_invoice).submit())
		self.step(f"Payment Entry · bayar via {self.payment_mode} + submit", self._pay_invoice)
		if not self.payment_entry:
			return False

		# Payment Entry submit -> hook Sales Invoice -> booking ikut Paid & auto-submit.
		bk = frappe.db.get_value("Container Booking", self.booking,
			["docstatus", "booking_status", "payment_status"], as_dict=True) or frappe._dict()
		return self.check("Booking · Paid + Confirmed + submitted setelah dibayar",
			bk.payment_status == "Paid" and bk.docstatus == 1 and bk.booking_status == "Confirmed",
			f"pay={bk.payment_status} docstatus={bk.docstatus} status={bk.booking_status}")

	def _pay_invoice(self):
		"""Payment Entry dari invoice-nya, memakai Mode of Payment yang dipilih.

		Akun kas/bank diambil dari Mode of Payment (tab Accounts per company) — persis
		yang dibaca form Payment Entry. Kalau mode yang dipilih belum dipetakan ke akun
		untuk company ini, langkah ini gagal, dan itu memang temuan yang mau dilihat.
		"""
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		account = frappe.db.get_value(
			"Mode of Payment Account",
			{"parent": self.payment_mode, "company": self.company},
			"default_account",
		)
		if not account:
			frappe.throw(
				f"Mode of Payment '{self.payment_mode}' belum punya akun default untuk company "
				f"{self.company} — Payment Entry tidak bisa menentukan akun kas/bank."
			)

		pe = get_payment_entry("Sales Invoice", self.sales_invoice)
		pe.mode_of_payment = self.payment_mode
		pe.paid_to = account
		# Mengganti paid_to WAJIB diikuti mata uang akunnya: ERPNext memvalidasi setiap
		# baris jurnal terhadap ``account_currency`` akun tujuan, dan kalau tidak ikut
		# diperbarui akan ditolak "can only be made in currency: ...".
		pe.paid_to_account_currency = frappe.db.get_value("Account", account, "account_currency")
		if pe.paid_to_account_currency != pe.paid_from_account_currency:
			# Kontraknya USD sementara kas depot IDR, jadi uang yang diterima harus
			# dikonversi. Kursnya diambil dari invoice-nya sendiri — supaya angka di kas
			# konsisten dengan piutang yang dilunasi, dan tidak perlu memanggil API kurs.
			pe.target_exchange_rate = flt(
				frappe.db.get_value("Sales Invoice", self.sales_invoice, "conversion_rate")) or 1
			pe.received_amount = flt(pe.paid_amount) * flt(pe.target_exchange_rate)
		else:
			pe.target_exchange_rate = 1
			pe.received_amount = pe.paid_amount
		pe.reference_no = self.tag
		pe.reference_date = today()
		pe.insert(ignore_permissions=True)
		self.payment_entry = pe.name
		self.track("Payment Entry", pe.name)
		pe.submit()
		return pe.name

	def _submit_booking(self):
		doc = frappe.get_doc("Container Booking", self.booking)
		doc.flags.ignore_permissions = True
		doc.submit()
		return doc.name

	# =======================================================================
	# 3) GATE IN — container fisik datang, lalu bon dibuat di gate
	# =======================================================================
	def gate_in(self):
		from container_depot import api

		self.booking_code = frappe.db.get_value("Booking Code",
			{"booking": self.booking, "container_no": CNO}, "name")
		self.track("Booking Code", self.booking_code)
		if not self.check("Booking Code · terbit saat booking submit", bool(self.booking_code)):
			return False
		self.check("Booking Code · statusnya Active (siap dipakai di gate)",
			frappe.db.get_value("Booking Code", self.booking_code, "state") == "Active")

		# Gate PWA membaca kode dulu sebelum apa pun — termasuk status pembayarannya.
		look = self.step("Gate · lookup booking code (PWA)", lambda: api.gate_lookup(self.booking_code))
		if isinstance(look, dict):
			self.check("Gate · lookup valid + tidak terblokir pembayaran",
				look.get("valid") and not look.get("payment_blocked"),
				f"valid={look.get('valid')} blocked={look.get('payment_blocked')}")

		res = self.step("Gate In · catat kedatangan container (PWA)",
			lambda: api.register_gate_entry(
				booking_code=self.booking_code, container_no=CNO,
				truck_plate="L-1234-SM", driver_name="Pak Sopir"))
		self.gate_entry = frappe.db.get_value("Gate Entry", {"container_no": CNO}, "name")
		self.track("Gate Entry", self.gate_entry)
		return self.check("Gate In · container masuk depot (In_Depot)",
			isinstance(res, dict) and res.get("success")
			and frappe.db.get_value("Container", CNO, "status") == "In_Depot",
			f"res={res} status={frappe.db.get_value('Container', CNO, 'status')}")

	# =======================================================================
	# 4) [1] ORDER BONGKAR — submit-nya yang menerbitkan EIR-In
	# =======================================================================
	def _gate_generate(self):
		from container_depot import api

		return api.gate_generate_order(
			self.booking,
			json.dumps([self.booking_code]),
			# Field yang diisi petugas di form gate: truk, sopir, kondisi, tanggal bongkar.
			vehicle_data=json.dumps({
				"truck_plate": "L-1234-SM",
				"driver": "Pak Sopir",
				"driver_phone": "081234567890",
				"condition": TANK_CONDITION,
				"tanggal_bongkar_actual": today(),
				"shipper": self.customer,
				"ex_vessel": "MV SMOKE TEST",
				"remarks": "smoke tank in",
			}),
		)

	def make_bon(self):
		res = self.step("Order Bongkar · generate bon dari gate + submit (PWA)", self._gate_generate)
		if not isinstance(res, dict):
			return False
		self.order_bongkar = res.get("order_name")
		self.track("Order Bongkar", self.order_bongkar)
		self.check("Order Bongkar · terbit submitted",
			res.get("order_doctype") == "Order Bongkar"
			and frappe.db.get_value("Order Bongkar", self.order_bongkar, "docstatus") == 1,
			f"res={res}")
		self.check("Booking Code · terpakai (Used) setelah bon terbit",
			frappe.db.get_value("Booking Code", self.booking_code, "state") == "Used")

		# Submit bon -> EIR-In draft ter-provision otomatis per container.
		self.eir = frappe.db.get_value("Inspection",
			{"container": CNO, "inspection_type": "EIR-In", "docstatus": 0}, "name")
		self.track("Inspection", self.eir)
		return self.check("EIR-In · draft ter-provision otomatis saat bon submit", bool(self.eir),
			f"order={self.order_bongkar}")

	# =======================================================================
	# 5) EIR-In — Empty Dirty + kerusakan
	# =======================================================================
	def fill_eir(self):
		from container_depot.ess import inspections as ess_eir

		self.step("EIR-In · buka draft (PWA)",
			lambda: ess_eir.eir_open_draft(container=CNO, inspection_type="EIR-In"))
		# Checklist terkunci sampai petugas menekan "Mulai" — itu yang menstempel jam mulai
		# kerja, jadi lama pemeriksaan terukur.
		self.step("EIR-In · tekan Mulai (PWA)", lambda: ess_eir.eir_start(inspection=self.eir))

		self.step("EIR-In · isi Empty Dirty + 1 posisi kerusakan lalu submit (PWA)",
			lambda: ess_eir.eir_save_draft(
				inspection=self.eir, inspection_type="EIR-In",
				tank_status="Empty Dirty",
				referred_voucher=self.order_bongkar,
				create_cleaning_order=1, create_repair_order=1,
				lines=self._damage_line(), submit=1))
		self.check("EIR-In · masuk antrean review Admin Ops (Pending Review)",
			frappe.db.get_value("Inspection", self.eir, "status") == "Pending Review")

		# Admin Ops yang mereview dan men-submit di Desk — itu yang memfinalkan EIR dan
		# menerbitkan follow-up-nya.
		self.step("EIR-In · review + submit Admin Ops (Desk)",
			lambda: frappe.get_doc("Inspection", self.eir).submit())
		return self.check("EIR-In · final (submitted)",
			frappe.db.get_value("Inspection", self.eir, "docstatus") == 1)

	def _damage_line(self):
		"""Satu posisi checklist yang benar-benar rusak.

		Kunci payload-nya ``item_code`` (kode posisi di Inspection Checklist Item, mis. "01"
		Underside), bukan nama doctype-nya. Damage code "v" (Acceptable) dan repair code "X"
		(No Action) artinya TIDAK rusak — baris begitu dibuang server dan tidak menerbitkan
		M&R, jadi di sini sengaja dipilih kode selain itu.
		"""
		from container_depot.container_depot.eir import ACCEPTABLE_DAMAGE_CODE, NO_ACTION_REPAIR_CODE

		item_code = frappe.db.get_value("Inspection Checklist Item", {}, "name", order_by="printed_no asc")
		damage = frappe.db.get_value(
			"Inspection Damage Code", {"name": ["!=", ACCEPTABLE_DAMAGE_CODE]}, "name", order_by="name asc")
		repair = frappe.db.get_value(
			"Inspection Repair Code", {"name": ["!=", NO_ACTION_REPAIR_CODE]}, "name", order_by="name asc")
		return [{
			"item_code": item_code,
			"damage_code": damage,
			"repair_code": repair,
			"remarks": "smoke: kerusakan uji",
		}]

	# =======================================================================
	# 6) [2] CLEANING ORDER — karena tanknya Empty Dirty
	# =======================================================================
	def do_cleaning(self):
		from container_depot.ess import cleaning as ess_cleaning

		self.cleaning_order = frappe.db.get_value("Cleaning Order", {"container": CNO}, "name")
		self.track("Cleaning Order", self.cleaning_order)
		if not self.check("Cleaning Order · terbit otomatis dari EIR Empty Dirty",
				bool(self.cleaning_order), f"eir={self.eir}"):
			return False
		self.check("Cleaning Order · mendarat di antrean Admin Ops (Service Setup)",
			frappe.db.get_value("Cleaning Order", self.cleaning_order, "status") == "Service Setup")

		# Admin Ops memilih metode cleaning-nya di Desk lalu meneruskan ke operator.
		# Servicenya hanya boleh yang ada di Service Menu "Cleaning" DAN berharga di
		# price list kontrak pemilik tank — itu isi picker-nya.
		self.step("Cleaning · pilih 1 service + teruskan ke operator (Desk)", self._forward_cleaning)
		self.check("Cleaning Order · masuk worklist operator (Pending)",
			frappe.db.get_value("Cleaning Order", self.cleaning_order, "status") == "Pending")

		# Operator mengerjakan dari PWA.
		self.step("Cleaning · buka detail (PWA)",
			lambda: ess_cleaning.cleaning_order_detail(self.cleaning_order))
		self.step("Cleaning · mulai kerjakan (PWA)",
			lambda: ess_cleaning.cleaning_start(self.cleaning_order))
		self.step("Cleaning · sign-off + submit (PWA)",
			lambda: ess_cleaning.cleaning_order_save(
				cleaning_order=self.cleaning_order, remarks="smoke: cleaning selesai", submit=1))
		return self.check("Cleaning Order · Completed + tersubmit",
			frappe.db.get_value("Cleaning Order", self.cleaning_order, "status") == "Completed"
			and frappe.db.get_value("Cleaning Order", self.cleaning_order, "docstatus") == 1)

	def _forward_cleaning(self):
		from container_depot.container_depot.doctype.cleaning_order.cleaning_order import (
			cleaning_item_query,
			service_pricing,
		)

		doc = frappe.get_doc("Cleaning Order", self.cleaning_order)
		options = cleaning_item_query("Item", "", "name", 0, 20, {"container": doc.container})
		if not options:
			frappe.throw("tidak ada service Cleaning yang berharga di kontrak pemilik tank")
		item = options[0][0]
		price = service_pricing(container=doc.container, item_code=item) or {}
		doc.append("cleaning_services", {
			"cleaning_item": item,
			"rate": price.get("rate") or 0,
			"manhour_rate": price.get("manhour_rate") or 0,
			"currency": price.get("currency"),
		})
		doc.status = "Pending"
		doc.save(ignore_permissions=True)
		return item

	# =======================================================================
	# 7) [3] REPAIR ORDER (M&R) — karena EIR menemukan kerusakan
	# =======================================================================
	def do_repair(self):
		from container_depot.ess import repairs as ess_mr

		self.repair_order = frappe.db.get_value("Repair Order", {"container": CNO}, "name")
		self.track("Repair Order", self.repair_order)
		if not self.check("Repair Order · terbit otomatis dari kerusakan di EIR",
				bool(self.repair_order), f"eir={self.eir}"):
			return False

		detail = self.step("M&R · buka order + kerusakan bawaan EIR (PWA)",
			lambda: ess_mr.mr_order_detail(self.repair_order))
		self.check("M&R · kerusakan dari EIR ikut terbawa",
			bool((detail or {}).get("damages")) if isinstance(detail, dict) else False)

		# Picker item M&R = Service Menu "Maintenance" ∩ price list kontrak — sama
		# aturannya dengan cleaning, jadi tarifnya selalu yang disepakati di kontrak.
		items = self.step("M&R · daftar service dari kontrak (PWA)",
			lambda: ess_mr.mr_items(repair_order=self.repair_order))
		rows = (items or {}).get("items") if isinstance(items, dict) else None
		if not self.check("M&R · ada service kontrak yang bisa dipakai", bool(rows), f"items={items}"):
			return False
		service = rows[0].get("item_code") or rows[0].get("name")

		self.step("M&R · isi 1 service dari kontrak (PWA)",
			lambda: ess_mr.mr_order_save(repair_order=self.repair_order,
				used_items=[{"item": service, "quantity": 1}]))
		# Estimasi naik ke Admin Ops dulu (Service Setup), baru ditampilkan ke owner.
		self.step("M&R · ajukan estimasi ke Admin Ops (PWA)",
			lambda: ess_mr.mr_submit_approval(repair_order=self.repair_order))
		self.step("M&R · Admin Ops tampilkan ke owner (PWA)",
			lambda: ess_mr.mr_publish_to_owner(repair_order=self.repair_order))
		self.check("M&R · menunggu keputusan owner (Pending Approval)",
			frappe.db.get_value("Repair Order", self.repair_order, "status") == "Pending Approval")

		self.step("M&R · owner menyetujui (Desk)",
			lambda: ess_mr.mr_decision(repair_order=self.repair_order, decision="Approved",
				line_decisions={service: "Approved"}))
		self.step("M&R · mulai pengerjaan (PWA)",
			lambda: ess_mr.mr_start(repair_order=self.repair_order))
		self.step("M&R · selesaikan (PWA)",
			lambda: ess_mr.mr_order_save(repair_order=self.repair_order, submit=1))
		return self.check("Repair Order · Completed",
			frappe.db.get_value("Repair Order", self.repair_order, "status") == "Completed")

	# =======================================================================
	# 8) POSISI AKHIR CONTAINER
	# =======================================================================
	def verify_container(self):
		"""Setelah semua pekerjaan selesai, tank harus berdiri bersih di depot.

		Catatan: tidak ada lagi doctype "Container Storage" / zona yard di app ini (dihapus
		2026-07-07). Keberadaan tank sekarang dibaca dari master Container: ``status``
		(Available = tidak ada pekerjaan terbuka) + ``inventory_stage``, plus riwayatnya di
		Container Activity — itu yang dilihat menu Monitor di PWA dan list Container di Desk.
		"""
		from container_depot.ess import inventory as ess_inv

		state = frappe.db.get_value("Container", CNO,
			["status", "inventory_stage", "depot", "principal"], as_dict=True) or frappe._dict()
		self.check("Container · Available (tidak ada pekerjaan terbuka lagi)",
			state.status == "Available", f"status={state.status}")
		self.check("Container · tercatat di depot + pemiliknya benar",
			state.depot and state.principal == self.customer,
			f"depot={state.depot} principal={state.principal}")

		# Terlihat dari menu Monitor (PWA) dan riwayat aktivitasnya lengkap.
		listing = self.step("Monitor · container muncul di daftar (PWA)",
			lambda: ess_inv.get_tank_list(search=CNO))
		self.check("Monitor · container ketemu di Monitor",
			any(r.get("name") == CNO or r.get("container_no") == CNO
				for r in (listing or {}).get("items", [])) if isinstance(listing, dict) else False)
		self.step("Monitor · detail container (PWA)", lambda: ess_inv.get_tank_detail(CNO))

		feed = {r.activity_type for r in frappe.get_all(
			"Container Activity", filters={"container": CNO}, fields=["activity_type"])}
		for needed in ("Booking", "Gate In", "Inspection (EIR)", "Cleaning"):
			self.check(f"Riwayat · ada aktivitas '{needed}'", needed in feed, f"ada={sorted(feed)}")

		# Batas jejak: tepat tiga order, semuanya turun dari booking/container yang sama.
		orders = {
			"Order Bongkar": self.order_bongkar,
			"Cleaning Order": self.cleaning_order,
			"Repair Order": self.repair_order,
		}
		return self.check("Jejak · tepat 3 order dalam satu rantai",
			len([v for v in orders.values() if v]) == 3
			and frappe.db.count("Container", {"container_no": CNO}) == 1,
			f"orders={orders}")

	# -- ringkasan ----------------------------------------------------------
	def summary(self):
		_log("\n" + "=" * 62)
		_log(f"SMOKE TANK IN — {self.passed} OK / {len(self.failed)} GAGAL  (tag {self.tag})")
		for label, detail in self.failed:
			_log(f"   GAGAL: {label} — {detail}")
		_log("=" * 62)
		return self.passed, len(self.failed)


# ---------------------------------------------------------------------------
# Teardown — hapus dokumen transaksi yang dibuat run ini. Masters seeder TIDAK disentuh.
# ---------------------------------------------------------------------------
def cleanup():
	"""Sapu semua dokumen ber-tag SMOKE, dalam urutan anak → induk.

	Sengaja raw delete: Container Booking dan Order * menolak dihapus lewat ``delete_doc``,
	dan dokumen bersubmit tidak bisa dihapus biasa. Aman karena satu rantai dihapus utuh,
	jadi tidak ada link menggantung. Sales Invoice / Payment Entry membawa jurnal, jadi
	baris GL-nya ikut dihapus.

	Yang TIDAK pernah dihapus: Customer, Depot Contract, Price List, Item, Depot, Branch —
	itu punya seeder, bukan punya test ini.
	"""
	removed = 0

	def names(doctype, filters):
		try:
			return frappe.get_all(doctype, filters=filters, pluck="name")
		except Exception:
			return []

	def purge(doctype, rows):
		nonlocal removed
		try:
			children = [df.options for df in frappe.get_meta(doctype).get_table_fields()]
		except Exception:
			children = []
		for name in rows:
			try:
				for child in children:
					frappe.db.delete(child, {"parent": name, "parenttype": doctype})
				frappe.db.delete(doctype, {"name": name})
				removed += 1
			except Exception as e:
				_log(f"   (lewati {doctype} {name}: {str(e).splitlines()[0][:70]})")

	containers = names("Container", {"container_no": CNO})
	bookings = names("Container Booking", {"do_reference": ["like", f"{DO_PREFIX}%"]})
	codes = names("Booking Code", {"container_no": CNO})
	orders_b = names("Order Bongkar", {"booking": ["in", bookings]}) if bookings else []
	orders_m = names("Order Muat", {"booking": ["in", bookings]}) if bookings else []
	gate = names("Gate Entry", {"container_no": CNO})
	eir = names("Inspection", {"container": ["in", containers]}) if containers else []
	clean = names("Cleaning Order", {"container": ["in", containers]}) if containers else []
	repair = names("Repair Order", {"container": ["in", containers]}) if containers else []
	# Sales Invoice-nya tidak menyimpan nomor booking di mana pun (remarks-nya hanya teks
	# generik), jadi satu-satunya jalur yang andal adalah field ``sales_invoice`` di
	# booking — dibaca SEBELUM booking-nya dihapus.
	invoices = [
		si for si in frappe.get_all("Container Booking", filters={"name": ["in", bookings or [""]]},
			pluck="sales_invoice") if si
	] if bookings else []
	payments = names("Payment Entry", {"reference_no": ["like", "SMOKE-%"]})
	payments += [
		p for p in (frappe.get_all("Payment Entry Reference",
			filters={"reference_doctype": "Sales Invoice", "reference_name": ["in", invoices or [""]]},
			pluck="parent") if invoices else [])
		if p not in payments
	]
	activity = names("Container Activity", {"container": ["in", containers]}) if containers else []
	movement = names("Container Movement", {"container": ["in", containers]}) if containers else []
	docs = set(containers + bookings + orders_b + orders_m + gate + eir + clean + repair)
	notif = names("Notification Log", {"document_name": ["in", list(docs) or [""]]}) if docs else []

	_log(f"cleanup: {len(containers)} container, {len(bookings)} booking, "
		f"{len(orders_b) + len(orders_m)} bon, {len(gate)} gate, {len(eir)} EIR, "
		f"{len(clean)} cleaning, {len(repair)} M&R, {len(invoices)} SI, {len(payments)} PE")

	# Jurnal dulu, baru vouchernya.
	for ledger in ("GL Entry", "Payment Ledger Entry"):
		for voucher in set(invoices + payments):
			try:
				frappe.db.delete(ledger, {"voucher_no": voucher})
			except Exception:
				pass

	for doctype, rows in (
		("Payment Entry", payments), ("Sales Invoice", invoices),
		("Gate Entry", gate), ("Inspection", eir),
		("Cleaning Order", clean), ("Repair Order", repair),
		("Order Muat", orders_m), ("Order Bongkar", orders_b),
		("Booking Code", codes), ("Container Booking", bookings),
		("Container Activity", activity), ("Container Movement", movement),
		("Notification Log", notif), ("Container", containers),
	):
		purge(doctype, rows)

	frappe.db.commit()
	_log(f"cleanup: {removed} dokumen dihapus.")
	return removed


# ---------------------------------------------------------------------------
def run(keep=0, cleanup_only=0, payment_mode="Cash"):
	frappe.set_user("Administrator")
	if int(cleanup_only or 0):
		return {"cleanup_only": True, "removed": cleanup()}

	# Sapu dulu sisa run sebelumnya — nomor container-nya tetap, jadi run kedua akan
	# bentrok kalau yang lama masih ada.
	cleanup()

	smoke = Smoke(keep=bool(int(keep or 0)), payment_mode=payment_mode)
	smoke.tag = f"SMOKE-{now_datetime().strftime('%Y%m%d%H%M%S')}"
	_log(f"\n########## SMOKE TANK IN ({smoke.tag}) ##########")
	# Alur Cash butuh invoicing. Kalau site-nya operations-only, nyalakan sebentar dan
	# kembalikan lagi di finally — jangan sampai run ini mengubah konfigurasi depot.
	finance_before = _set_finance(True)
	try:
		if smoke.ensure_masters():
			if smoke.create_booking() and smoke.settle() and smoke.gate_in() and smoke.make_bon():
				smoke.fill_eir()
				smoke.do_cleaning()
				smoke.do_repair()
				smoke.verify_container()
	finally:
		if smoke.keep:
			_log("keep=1 → data dibiarkan (ingat jalankan cleanup_only=1 nanti).")
			frappe.db.commit()
		else:
			cleanup()
		_set_finance(finance_before)
	passed, failed = smoke.summary()
	return {"tag": smoke.tag, "passed": passed, "failed": failed}
