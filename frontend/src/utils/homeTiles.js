// Kartu "Hari ini" mana yang tampil di Beranda — pilihan operator, maksimal empat.
//
// Kartunya ada sebelas (satu-dua per menu), tapi yang muat di layar HP tanpa mendorong
// "Menunggu Anda" ke bawah lipatan cuma empat. Yang empat itu berbeda per pekerjaan: kepala
// gate hidup di Tank masuk/keluar, tim yard di Letak Tank dan antrean lowering, admin ops di
// EIR review. Empat bawaan di bawah adalah yang tampil sebelum pemilihan ini ada, jadi
// handset yang pemiliknya tidak pernah memilih tidak berubah sama sekali.
//
// Kuncinya dikirim ke server sebagai param `tiles` (ess/home.py): yang tidak dipilih tidak
// dihitung sama sekali, jadi katalog boleh tumbuh tanpa memperlambat pembukaan aplikasi.

import { createPicks } from "@/utils/userPicks"

export const MAX_TILES = 4
export const DEFAULT_TILES = ["gateIn", "gateOut", "eirReview", "cleaning"]

const picks = createPicks("oak-home-tiles", MAX_TILES)

export const pickedTiles = picks.picked
export const setTiles = picks.set
export const resetTiles = picks.reset
