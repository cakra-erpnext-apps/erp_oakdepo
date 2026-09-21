// Kartu "Hari ini" mana yang tampil di Beranda — pilihan operator, sebanyak yang ia mau.
//
// Kartunya ada sebelas (satu-dua per menu) dan semuanya boleh dipasang sekaligus; yang
// bawaan cuma empat, karena itu yang muat di layar HP tanpa mendorong "Menunggu Anda" ke
// bawah lipatan. Empat yang mana pun berbeda per pekerjaan: kepala gate hidup di Tank
// masuk/keluar, tim yard di Letak Tank dan antrean lowering, admin ops di EIR review.
// Empat bawaan di bawah adalah yang tampil sebelum pemilihan ini ada, jadi handset yang
// pemiliknya tidak pernah memilih tidak berubah sama sekali.
//
// Kuncinya dikirim ke server sebagai param `tiles` (ess/home.py): yang tidak dipilih tidak
// dihitung sama sekali, jadi memasang sebelas kartu adalah biaya yang operator pilih
// sendiri, bukan yang ditanggung semua orang.

import { createPicks } from "@/utils/userPicks"

export const DEFAULT_TILES = ["gateIn", "gateOut", "eirReview", "cleaning"]

const picks = createPicks("oak-home-tiles")

export const pickedTiles = picks.picked
export const setTiles = picks.set
export const resetTiles = picks.reset
