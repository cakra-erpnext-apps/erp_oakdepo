// Pekerjaan yang sudah dipegang orang lain.
//
// Sekali seorang operator menekan "Mulai", EIR / Cleaning Order / M&R itu hilang dari
// worklist operator lain (server yang menyaringnya — lihat container_depot/work_claim.py).
// Yang TIDAK bisa disaring worklist adalah tautan notifikasi: bel dikirim ke seluruh role,
// jadi rekan yang menekannya sedetik kemudian tetap mendarat di form yang sudah diambil.
// Server menolaknya dengan exc_type `ClaimedByAnother`, dan di sinilah layar membacanya:
// tampilkan toast berisi kalimat dari server (sudah menyebut nama pemegangnya) lalu
// pulangkan operator ke worklist — bukan biarkan dia mengisi form yang pasti ditolak
// waktu autosave.
const CLAIMED = "ClaimedByAnother"

/** Penolakan karena order ini sedang dipegang akun lain? */
export function isClaimed(err) {
	return err?.exc_type === CLAIMED
}

/** Kalimat penolakan dari server (sudah menyebut siapa yang memegang). */
export function claimMessage(err) {
	return err?.messages?.[0] || err?.message || ""
}
