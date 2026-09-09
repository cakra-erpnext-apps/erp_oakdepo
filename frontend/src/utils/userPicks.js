// Pilihan tampilan kecil milik satu operator — tab bar bawah, kartu "Hari ini".
//
// Bukan data: tidak ada laporan yang membacanya, tidak ada yang rusak kalau ia hilang, dan
// mengembalikannya ke bawaan selalu aman. Karena itu ia tinggal di localStorage, bukan di
// server — berlaku seketika, tetap jalan saat handset tanpa sinyal, dan tidak menambah satu
// pun round-trip ke pembukaan aplikasi.
//
// Selalu DIKUNCI PER USER. Handset depo berpindah tangan antar shift dan tiap akun memegang
// modul yang berbeda; menyimpannya per perangkat berarti operator berikutnya mewarisi
// pilihan orang sebelumnya — menunjuk ke layar yang bahkan tidak boleh ia buka. Yang
// menyaring tetap permission (`menu.has`), pilihan ini cuma menentukan urutan dan jumlah.

import { reactive, watch } from "vue"

/**
 * Satu penyimpan pilihan: `picked(user)` mengembalikan array kunci, atau `null` kalau akun
 * itu belum pernah memilih — dan `null` BERBEDA dari array kosong, yang berarti "saya
 * memang tidak mau satu pun".
 */
export function createPicks(storageKey, max) {
	const state = reactive({ byUser: read() })

	function read() {
		try {
			const saved = JSON.parse(localStorage.getItem(storageKey) || "null")
			// { "budi@oak.co.id": ["monitor", "tankPos"] } — bentuk lain diabaikan.
			return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {}
		} catch {
			return {}
		}
	}

	watch(
		() => state.byUser,
		(v) => {
			try {
				localStorage.setItem(storageKey, JSON.stringify(v))
			} catch {
				/* mode privat: pilihan tetap berlaku sampai aplikasi ditutup */
			}
		},
		{ deep: true }
	)

	return {
		max,
		picked(user) {
			const keys = state.byUser[user]
			return Array.isArray(keys) ? keys : null
		},
		set(user, keys) {
			if (user) state.byUser[user] = [...new Set(keys)].slice(0, max)
		},
		reset(user) {
			if (user) delete state.byUser[user]
		},
	}
}
