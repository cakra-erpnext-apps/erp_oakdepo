<template>
	<span v-if="due" class="oak-chip shrink-0 whitespace-nowrap" :class="chipClass">
		<Icon :name="urgent ? 'alert-triangle' : liftIcon(due)" :size="11" />
		<template v-if="urgent">MENDESAK · </template>{{ hMinus(due) }} · {{ fmtDayMonth(due) }}
	</span>
</template>

<script setup>
// Prioritas satu baris worklist: kapan pekerjaan ini harus sudah beres (lihat utils/liftOn.js).
//
// Tenggatnya hari SURVEY, bukan hari pickup: di hari itulah tank harus sudah turun, bersih,
// diperbaiki dan siap diperiksa. Hari pickup dipakai hanya sebagai cadangan, untuk booking
// yang hari survey-nya belum ditentukan — tetap sebuah tenggat, dan menjatuhkannya ke dasar
// daftar hanya akan menyembunyikannya.
//
// Sebuah komponen, bukan enam salinan potongan markup yang sama: keenam worklist (EIR,
// EIR review, Cleaning, M&R, Fix Posisi) menampilkan badge ini, dan yang membuatnya berguna
// justru karena bunyinya sama persis di semua layar — "H-3" harus berarti dan terlihat sama
// di mana pun operator membacanya. Enam salinan pada akhirnya akan berselisih.
//
// Hitung mundur DAN tanggalnya, bukan salah satu. "H-2" menjawab seberapa mendesak — itu yang
// dipakai mengurutkan pekerjaan hari ini — tapi tidak bisa dipakai bicara: menjanjikan sesuatu
// ke pelanggan, menulis di papan, atau mencocokkan dengan bon di tangan semuanya butuh
// "9 Sep". Menghitung sendiri dari "H-2" berarti aritmetika tanggal di HP, di lapangan, dan
// itu persis jenis kekeliruan yang baru ketahuan setelah truknya datang.
//
// Tanpa kata "Lift-on" di depannya: di worklist ini prioritas hanya pernah berarti satu hal,
// yaitu kapan tank dijemput, jadi katanya mengulang konteks yang sudah pasti — dan ia yang
// paling mahal, memakan ~45 px di baris chip yang harus berbagi dengan status dan voucher.
// Yang tersisa justru dua hal yang benar-benar dibaca: seberapa mendesak, dan tanggal berapa.
import { computed } from "vue"

import { hMinus, liftChipClass, liftIcon } from "@/utils/liftOn"
import { fmtDayMonth } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	// Tanggal survey booking (`target_survey_on`) — tenggat sebenarnya pekerjaan ini.
	survey: { type: String, default: "" },
	// Rencana pickup (`target_lift_on`), dipakai kalau hari survey-nya belum ditentukan.
	target: { type: String, default: "" },
	// Tanggal mendesak (`target_urgent_on`) — dipasang manual oleh SPV / Admin Ops di booking,
	// dan mengalahkan kedua tanggal di atas. Terisi = baris ini ada di tier teratas semua
	// worklist (`worklist.sort_by_priority`).
	urgent: { type: String, default: "" },
})

// Mendesak MENGGANTIKAN chip-nya, bukan menambah chip kedua: begitu ada tanggal mendesak,
// dialah tenggat yang dipakai server mengurutkan baris ini, jadi memajang tanggal survey di
// sebelahnya berarti memajang tanggal yang bukan lagi penentu urutannya. Baris chip di HP
// juga cuma muat sedikit, dan ia sudah berbagi dengan status dan voucher.
const urgent = computed(() => !!props.urgent)

// Merah penuh, bukan sekadar satu tingkat lagi di tanjakan warna biasa: mendesak bukan "H-1
// sekali lagi", ia kategori lain — satu-satunya hal yang boleh mendahului pekerjaan yang
// harinya sudah tiba. Diberi ring supaya tetap terbaca sebagai chip di atas kartu putih.
const chipClass = computed(() =>
	urgent.value ? "bg-red-600 text-white ring-1 ring-red-700" : liftChipClass(props.survey || props.target),
)

// Satu tanggal yang ditampilkan, dan ia harus tanggal yang sama dengan yang dipakai server
// mengurutkan daftarnya (`worklist.priority_date`) — antrean yang diurutkan tanggal A tapi
// setiap barisnya menampilkan tanggal B lebih membingungkan daripada dua-duanya sendirian.
const due = computed(() => props.urgent || props.survey || props.target)
</script>
