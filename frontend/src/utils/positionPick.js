// Tank yang sudah dipilih saat berpindah ke layar "Catat sekaligus".
//
// Baris tank-nya SUDAH ada di layar yang menyerahkan (daftar "belum terdata" membawanya
// lengkap: nomor, prinsipal, posisi sebelumnya). Mengirim hanya nomornya lewat query lalu
// mencarinya kembali satu per satu berarti membayar sekali lagi untuk data yang sudah ada di
// tangan — dan di sinyal yard, membuat layar berikutnya terbuka kosong lebih dulu.
//
// Sekali pakai: diambil berarti habis. Kalau tidak, kembali ke layar itu lewat tombol Back
// akan memilih ulang tank yang tadi sudah sengaja dilepas.
let pending = []

export function setPreselect(rows) {
	pending = Array.isArray(rows) ? [...rows] : []
}

export function takePreselect() {
	const out = pending
	pending = []
	return out
}

// Alur lowering memakai pola yang sama, dan sengaja memakai laci sendiri: dua layar yang
// menitipkan barisnya ke satu variabel akan saling mencuri pilihan begitu keduanya pernah
// dibuka dalam satu sesi.
let pendingLowering = []

export function setLoweringPreselect(rows) {
	pendingLowering = Array.isArray(rows) ? [...rows] : []
}

export function takeLoweringPreselect() {
	const out = pendingLowering
	pendingLowering = []
	return out
}
