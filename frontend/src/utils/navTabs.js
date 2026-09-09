// Tab mana yang duduk di bar bawah — pilihan operator, bukan urutan bawaan.
//
// `TAB_ORDER` di data/modules.js memutuskan bar untuk akun yang memegang banyak modul, dan
// urutannya benar untuk kebanyakan orang: Gate, EIR, M&R adalah tiga layar tempat satu shift
// dihabiskan. Tapi "kebanyakan orang" bukan semua: operator yard menghabiskan harinya di
// Monitor dan Letak Tank, dan bagi mereka dua modul yang paling sering dibuka justru selalu
// bersembunyi satu ketukan di dalam "Lainnya".
//
// Yang bisa dipilih hanya SLOT TENGAH. Beranda dan Lainnya tetap di tempatnya: yang pertama
// adalah satu-satunya halaman yang boleh dibuka setiap akun (dan tempat keadaan kosong
// tinggal), yang kedua adalah pintu ke semua modul lain — termasuk ke pengaturan ini
// sendiri. Bar tanpa keduanya bisa mengunci operator di layar tanpa jalan keluar.

import { createPicks } from "@/utils/userPicks"

/** Lima slot: Beranda + tiga + Lainnya. Lebih dari ini dan tiap tab menyempit di bawah
 *  lebar jempol pada HP 320 px — lihat komentar tinggi/lebar sentuh di BottomNav.vue. */
export const MAX_TABS = 3

const picks = createPicks("oak-nav-tabs", MAX_TABS)

export const pickedTabs = picks.picked
export const setTabs = picks.set
/** Kembali ke urutan bawaan (TAB_ORDER). */
export const resetTabs = picks.reset
