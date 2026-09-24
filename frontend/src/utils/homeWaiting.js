// Susunan "Menunggu Anda" di Beranda — antrean mana yang tampil dan urutannya, pilihan
// operator. Tanpa pilihan: semua antrean, tertua di atas (urutan server).
//
// Disimpan di HP (localStorage, dikunci per user — lihat userPicks.js), sama seperti kartu
// "Hari ini". Kuncinya dikirim ke server sebagai param `waiting` (ess/home.py), supaya
// pemotongan delapan baris jatuh setelah susunan operator, bukan sebelumnya.

import { createPicks } from "@/utils/userPicks"

const picks = createPicks("oak-home-waiting")

export const pickedWaiting = picks.picked
export const setWaiting = picks.set
export const resetWaiting = picks.reset
