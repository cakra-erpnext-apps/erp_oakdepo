<template>
	<section v-if="steps.length" class="oak-card space-y-3 p-4">
		<p class="oak-section-title">{{ labels.mrFlowTitle }}</p>
		<ol class="space-y-3">
			<li v-for="(s, i) in steps" :key="s.label" class="relative flex gap-3 pl-1">
				<!-- Garis penghubung digambar oleh titiknya sendiri, bukan elemen tersendiri:
				     satu pseudo-border yang berhenti di langkah terakhir, jadi tidak ada ekor
				     menggantung di bawah baris paling bawah. -->
				<span class="relative flex w-2.5 shrink-0 justify-center">
					<span class="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" :class="s.tone"></span>
					<span
						v-if="i < steps.length - 1"
						class="absolute left-1/2 top-4 h-[calc(100%+0.25rem)] w-px -translate-x-1/2 bg-gray-200"
					></span>
				</span>
				<div class="min-w-0 flex-1 pb-0.5">
					<p class="truncate text-sm font-bold text-gray-900">{{ s.label }}</p>
					<p class="text-xs text-gray-500">{{ s.detail }}</p>
				</div>
			</li>
		</ol>
	</section>
</template>

<script setup>
// Riwayat satu M&R sebagai empat baris: diajukan, diputuskan, dikerjakan, dikirim.
//
// Tabel "Diajukan ke Owner / Keputusan Owner / Mulai Dikerjakan" yang lama memuat cap waktu
// yang sama persis, tapi sebagai daftar istilah — dan urutannya hilang. Pertanyaan yang
// benar-benar ditanyakan orang tentang order lama selalu berbentuk urutan: siapa
// meloloskannya, kapan mulai dipegang, dan sekarang nunggu siapa.
//
// Tidak ada langkah yang dikarang: tiap baris hanya muncul kalau cap waktunya memang ada.
// Satu-satunya pengecualian adalah "Dikirim untuk review" pada order yang statusnya memang
// Menunggu Review — order itu beku di server, jadi `modified`-nya memang detik pengirimannya
// (lihat `submitted_on` di mr.py). Di luar itu langkahnya tampil tanpa jam, bukan dengan jam
// yang mengarang.
import { computed } from "vue"

import { labels } from "@/utils/labels"
import { fmtStamp } from "@/utils/mrStatus"

const props = defineProps({
	// Payload `mr_order_detail`.
	data: { type: Object, required: true },
})

const DONE = "bg-leaf-500"
const NOW = "bg-brand-500" // langkah terakhir: di sinilah order itu berdiri sekarang

const steps = computed(() => {
	const d = props.data
	const rows = []
	const push = (label, stamp, detail) => rows.push({ label, detail: [fmtStamp(stamp) || labels.mrFlowNoTime, detail].filter(Boolean).join(" · "), tone: DONE })

	if (d.requested_on) push(labels.mrFlowRequested, d.requested_on, d.revision_no ? `${labels.mrRevisionNo} ${d.revision_no}` : "")
	if (d.decided_on) {
		const rejected = d.status === "Rejected"
		push(rejected ? labels.mrRejectedBanner : labels.mrFlowApproved, d.decided_on, [d.decided_by_name, d.owner_note].filter(Boolean).join(" · "))
		if (rejected) rows[rows.length - 1].tone = "bg-red-500"
	}
	if (d.start_date) push(labels.mrFlowStarted, d.start_date, d.started_by_name || d.technician || "")
	if (d.status === "Pending Review") push(labels.mrFlowReview, d.submitted_on, labels.mrFlowReviewWait)
	if (d.completion_date) push(labels.mrFlowDone, d.completion_date, "")

	if (rows.length) rows[rows.length - 1].tone = NOW
	return rows
})
</script>
