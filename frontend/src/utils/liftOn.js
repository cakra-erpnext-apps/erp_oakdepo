// The outbound booking's target lift-on → the countdown badge every worklist shows.
//
// One definition for every worklist (EIR, Cleaning, M&R, Survey Posisi, Fix Posisi): the
// badge is a vocabulary an operator learns once — "H-3" is three days to pickup, "Hari-H" is
// today, "Lewat 2 hr" is two days overdue — and a second copy of it would eventually
// disagree about the colour of urgency, which is the one thing the badge exists to say.
//
// The stamp is a plain date, so it is compared date-to-date in local time: parsing it as
// "YYYY-MM-DDT00:00:00" (rather than letting Date treat a bare date as UTC) keeps H-0 on the
// day the customer actually comes, in Jakarta rather than in London.
export const liftDays = (v) => {
	if (!v) return null
	const target = new Date(String(v).slice(0, 10) + "T00:00:00")
	const today = new Date(new Date().toDateString())
	return Math.round((target - today) / 86400000)
}

export const hMinus = (v) => {
	const d = liftDays(v)
	if (d === null) return ""
	if (d < 0) return `Lewat ${-d} hr`
	if (d === 0) return "Hari-H"
	return `H-${d}`
}

/**
 * Warna badge-nya — satu tanjakan mendesak, bukan sekadar teks berwarna.
 *
 * Dulu ini cuma `text-*`: tulisan berwarna di antara tulisan berwarna lain, satu-satunya
 * pembeda dari nomor EIR abu-abu di sebelahnya adalah rona. Di baris worklist yang sudah
 * memuat chip "Sedang dikerjakan" dan chip jenis cleaning, prioritas justru jadi hal paling
 * tidak kelihatan padahal dialah yang menentukan tank mana dikerjakan duluan. Sekarang
 * berlatar, sejajar dengan chip lain di baris yang sama (lihat LiftOnBadge.vue).
 *
 * Ambangnya persis seperti sebelumnya (<=1 hari merah, <=3 kuning) supaya kosakata yang
 * sudah dihafal operator tidak bergeser. Yang berubah cuma ujung jauhnya: dulu oranye
 * brand — tetangga dekat kuning, jadi H-7 dan H-3 nyaris tak terbedakan sekilas, dan di
 * baris Cleaning ia bertabrakan dengan chip jenis cleaning yang juga brand. Abu-abu
 * membuat tanjakannya terbaca sebagai tanjakan: diam → kuning → merah → merah penuh.
 */
export const liftChipClass = (v) => {
	const d = liftDays(v)
	if (d === null) return ""
	if (d < 0) return "bg-red-600 text-white"
	if (d <= 1) return "bg-red-100 text-red-700 ring-1 ring-red-200"
	if (d <= 3) return "bg-amber-100 text-amber-800"
	return "bg-gray-100 text-gray-600"
}

/** Lewat tenggat pantas dapat ikonnya sendiri: warna saja menuntut perbandingan dengan
 *  baris lain, bentuk tidak. */
export const liftIcon = (v) => (liftDays(v) < 0 ? "alert-triangle" : "calendar")
