<template>
	<!-- Satu sel di dalam <dl> spesifikasi tank, dengan satu tombol lebih banyak dari sel
	     lainnya: tanggal ini adalah satu-satunya baris di kartu itu yang bisa diketahui oleh
	     orang yang sedang membacanya dan tidak diketahui oleh sistem. -->
	<!-- Saat diedit ia mengambil kedua kolom: sebuah date picker yang dipaksa masuk setengah
	     lebar layar HP adalah kotak yang tidak bisa dibaca sambil diketik. -->
	<div class="min-w-0" :class="editing ? 'col-span-2' : ''">
		<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.lastTest }}</dt>
		<dd v-if="editing">
			<input
				ref="input"
				v-model="draft"
				type="date"
				:max="today"
				class="oak-input mt-1 !px-2 !py-1.5 text-sm"
			/>
			<p class="mt-1 text-[11px] leading-snug text-gray-500">{{ labels.lastTestHint }}</p>
			<div class="mt-1.5 flex gap-2">
				<button
					type="button"
					class="oak-btn oak-btn-primary !px-3 !py-1.5 !text-xs"
					:disabled="!draft || saving"
					@click="save"
				>
					{{ labels.lastTestSave }}
				</button>
				<button
					type="button"
					class="oak-btn oak-btn-ghost !px-3 !py-1.5 !text-xs"
					:disabled="saving"
					@click="editing = false"
				>
					{{ labels.lastTestCancel }}
				</button>
			</div>
		</dd>
		<dd v-else class="flex items-baseline gap-2">
			<span class="min-w-0 truncate font-semibold text-gray-800">{{ shown || "—" }}</span>
			<button
				v-if="container"
				type="button"
				class="shrink-0 text-[11px] font-semibold text-brand-600"
				@click="start"
			>
				{{ modelValue ? labels.lastTestEdit : labels.lastTestAdd }}
			</button>
		</dd>
	</div>
</template>

<script setup>
// Tgl. Tes Terakhir, bisa dibetulkan dari layar order.
//
// Nilainya milik TANK (`Container.last_test_date`), bukan milik order yang kebetulan sedang
// terbuka — tidak ada salinan per-order, karena salinan berarti satu tank punya dua jawaban
// dan yang tercetak di EIR berikutnya adalah lemparan koin. Karena itu komponen ini menulis
// ke master lewat satu endpoint (`ess.inventory.set_tank_last_test`) dan memberi tahu
// induknya nilai barunya, bukan menitipkannya ke autosave order.
//
// Uji berkala yang dikerjakan di depo sendiri mengisi field ini otomatis saat M&R-nya
// selesai (RepairOrder._stamp_last_test_date). Yang diketik di sini adalah uji yang terjadi
// di luar: di vendor, di depo lain, atau sebelum tank ini pernah masuk ke sini — satu-satunya
// jalan agar riwayat tank tidak terputus di pagar depo.
import { computed, nextTick, ref } from "vue"

import { send } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"

const props = defineProps({
	container: { type: String, default: "" }, // nama Container; kosong = tampil saja
	modelValue: { type: String, default: "" }, // ISO date dari master
})
const emit = defineEmits(["update:modelValue"])

const editing = ref(false)
const saving = ref(false)
const draft = ref("")
const input = ref(null)
const today = new Date().toISOString().slice(0, 10)

// dd-mm-yyyy: tanggal di depo dibaca begitu, dan sebuah "2024-03-11" di tengah kartu berisi
// angka lain selalu sempat terbaca sebagai sesuatu yang lain dulu.
const fmt = (v) => {
	const iso = String(v || "").slice(0, 10)
	if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return v || ""
	const [y, m, d] = iso.split("-")
	return `${d}-${m}-${y}`
}
// Turunan dari prop, bukan salinan: induknya memuat ulang order setelah aksi lain, dan sel
// yang menyimpan nilainya sendiri akan tetap menampilkan tanggal lama.
const shown = computed(() => fmt(props.modelValue))

function start() {
	draft.value = String(props.modelValue || "").slice(0, 10)
	editing.value = true
	nextTick(() => input.value?.focus())
}

async function save() {
	if (!draft.value || saving.value) return
	saving.value = true
	try {
		const r = await send({
			url: "container_depot.ess.inventory.set_tank_last_test",
			payload: { container: props.container, last_test_date: draft.value },
		})
		// Server yang menentukan nilai akhirnya (ia yang menormalkan tanggalnya), jadi itu
		// yang dipakai — bukan apa yang diketik.
		const saved = r?.message?.last_test_date || draft.value
		emit("update:modelValue", saved)
		editing.value = false
		toast.success(labels.lastTestSaved)
	} catch (e) {
		toast.error(e?.message || String(e))
	} finally {
		saving.value = false
	}
}
</script>
