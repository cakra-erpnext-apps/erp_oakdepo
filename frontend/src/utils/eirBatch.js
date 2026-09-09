// Satu bon, beberapa tank — dan satu batch yang menyatukannya.
//
// Truk datang per bon, bukan per tank: satu Order Bongkar melepas dua, tiga, kadang enam
// tank sekaligus, dan semuanya membawa data rujukan yang sama (kode booking, EMKL, truk,
// sopir). Sebelum ini setiap EIR dikerjakan sebagai pulau sendiri — kembali ke daftar,
// cari tank berikutnya, ketik ulang data bon yang sama.
//
// Batch = himpunan EIR yang dipilih operator di daftar, ditambah apa yang hanya masuk akal
// selama batch itu terbuka:
//
//   steps      langkah terakhir tiap EIR, supaya membuka ulang tank yang sama mendarat di
//              tempat yang ditinggalkan (dan daftar bisa menulis "Draft 2/4").
//   startedAt  jam mulai versi HP. Jam server dipakai sebagai cadangan, tapi selisih zona
//              waktu antara handset dan site membuat penghitung waktu melompat berjam-jam;
//              angka yang dicetak di layar harus berasal dari jam yang sama dengan yang
//              menghitungnya.
//   sent       EIR yang sudah dikirim dari batch ini, dengan ringkasannya. Baris yang
//              dikirim hilang dari daftar pending, jadi tanpa catatan ini layar "batch
//              selesai" tidak punya apa-apa untuk ditampilkan.
//
// localStorage dengan umur, bukan sessionStorage. sessionStorage adalah pilihan pertama
// yang salah: ia mati bersama "sesi browsing", dan di HP depo itu terjadi setiap kali
// Android membunuh PWA di latar belakang — yang paling sering justru sesudah kamera dibuka,
// tepat di tengah batch. Operator kembali dan batch-nya lenyap. localStorage selamat dari
// itu; cap waktu di bawah yang menjaga supaya ia tidak menyambut shift berikutnya besok
// pagi. Cap waktunya hanya hidup di storage, tidak di state — kalau ia ikut reaktif, setiap
// penyimpanan akan memicu penyimpanan berikutnya.

import { reactive, watch } from "vue"

const KEY = "eir_batch_v2"
// Sisa satu shift, dengan kelonggaran. Lebih lama dari ini dan sebuah batch yang terlupakan
// akan muncul lagi di tangan orang lain sebagai pekerjaan yang seolah masih berjalan.
const MAX_AGE_MS = 12 * 60 * 60 * 1000

/** Jumlah langkah form EIR — dipakai daftar untuk mencetak "Draft 2/4". */
export const STEP_COUNT = 4

function blank() {
	return { names: [], tank: {}, voucher: "", steps: {}, startedAt: {}, sent: {} }
}

function read() {
	try {
		const saved = JSON.parse(localStorage.getItem(KEY) || "null")
		if (saved && Array.isArray(saved.names) && Date.now() - (saved.savedAt || 0) < MAX_AGE_MS) {
			const rest = { ...saved }
			delete rest.savedAt // cap waktu milik storage, bukan bagian dari state
			return { ...blank(), ...rest }
		}
	} catch {
		/* storage rusak / diblokir — mulai dari kosong */
	}
	return blank()
}

export const batch = reactive(read())

watch(
	batch,
	(v) => {
		try {
			localStorage.setItem(KEY, JSON.stringify({ ...v, savedAt: Date.now() }))
		} catch {
			/* mode privat: batch tetap jalan, cuma tidak selamat dari aplikasi ditutup */
		}
	},
	{ deep: true }
)

/** Batch yang benar-benar batch: satu EIR sendirian tidak perlu bar maupun sheet. */
export function inBatch(name) {
	return batch.names.length > 1 && batch.names.includes(name)
}

/**
 * Buka daftar EIR terpilih sebagai satu batch. `voucher` hanya diisi kalau semuanya
 * memang dari bon yang sama — itu yang membuat kalimat "voucher sama dengan FG01" boleh
 * dipercaya di layar berikutnya.
 */
export function openBatch(members, voucher = "") {
	batch.names = members.map((m) => m.name)
	// Nomor tank ikut disimpan: form EIR hanya memuat tank-nya sendiri, sementara kartu
	// "Status batch" di langkah terakhir harus menyebut anggota lain dengan nama yang
	// dikenal operator — bukan nama dokumen.
	batch.tank = Object.fromEntries(members.map((m) => [m.name, m.container_no || ""]))
	batch.voucher = voucher || ""
	batch.sent = {}
}

/** Nomor tank satu anggota batch. */
export function tankNo(name) {
	return batch.tank[name] || ""
}

/** Keluar dari batch — langkah dan jam mulai ikut dibuang, catatan kiriman tidak lagi relevan. */
export function leaveBatch() {
	Object.assign(batch, blank())
}

export function setStep(name, step) {
	if (name) batch.steps[name] = step
}

/** Pernahkah langkah EIR ini dicatat? Baris worklist hanya boleh menulis "Draft 2/4"
 *  untuk EIR yang benar-benar pernah dibuka di sesi ini — bukan menebak "1/4" untuk semua. */
export function hasStep(name) {
	return Object.prototype.hasOwnProperty.call(batch.steps, name)
}

export function getStep(name) {
	const s = batch.steps[name]
	return Number.isInteger(s) && s >= 0 && s < STEP_COUNT ? s : 0
}

/** Jam mulai versi HP, dipasang saat tombol Mulai ditekan. */
export function markStarted(name) {
	if (name) batch.startedAt[name] = Date.now()
}

/**
 * Titik nol penghitung waktu, dalam ms. Pakai jam HP kalau EIR ini dimulai di sesi ini;
 * kalau tidak (dibuka ulang setelah refresh) baru jatuh ke cap waktu server. Mengembalikan
 * 0 kalau tidak ada keduanya — pemanggilnya menyembunyikan penghitung, bukan mencetak
 * angka yang dikarang.
 */
export function startMs(name, serverStamp) {
	const local = batch.startedAt[name]
	if (local) return local
	if (!serverStamp) return 0
	const t = new Date(String(serverStamp).replace(" ", "T")).getTime()
	return Number.isFinite(t) ? t : 0
}

/**
 * Catat satu EIR yang baru dikirim, dengan ringkasan yang dibaca layar "batch selesai".
 * Namanya TIDAK dibuang dari batch: bar dan sheet tetap harus bisa menunjukkan bahwa tank
 * itu ada dan sudah beres — antrean kerja adalah anggota yang belum dikirim (lihat
 * `pendingNames`), bukan daftar anggotanya.
 */
export function markSent(name, info) {
	batch.sent[name] = { at: Date.now(), ...info }
}

/** Anggota batch yang masih harus dikerjakan. */
export function pendingNames() {
	return batch.names.filter((n) => !batch.sent[n])
}

/** Ringkasan kiriman batch ini, urut waktu kirim. */
export function sentRows() {
	return Object.entries(batch.sent)
		.map(([name, info]) => ({ name, ...info }))
		.sort((a, b) => a.at - b.at)
}

/** Masih ada anggota batch yang belum dikirim? */
export function hasPending() {
	return pendingNames().length > 0
}
