<template>
	<!-- Satu sel di <dl> spesifikasi tank, tapi berupa isian biasa: tanggal ini satu-satunya
	     baris di kartu itu yang bisa diketahui orang yang membacanya dan tidak oleh sistem.
	     Dua kolom penuh: date picker setengah lebar layar HP tidak terbaca sambil diketik. -->
	<div class="col-span-2 min-w-0">
		<label :for="id" class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.lastTest }}</label>
		<input
			:id="id"
			:value="String(modelValue || '').slice(0, 10)"
			type="date"
			:max="today"
			:disabled="!container || saving"
			class="oak-input mt-1 !px-2 !py-1.5 text-sm"
			@change="save($event.target)"
		/>
		<p class="mt-1 text-[11px] leading-snug text-gray-500">{{ labels.lastTestHint }}</p>
	</div>
</template>

<script setup>
// Tgl. Tes Terakhir, diisi langsung di form order.
//
// Nilainya milik TANK (`Container.last_test_date`), bukan milik order yang kebetulan sedang
// terbuka — tidak ada salinan per-order, karena salinan berarti satu tank punya dua jawaban
// dan yang tercetak di EIR berikutnya adalah lemparan koin. Karena itu komponen ini menulis
// ke master lewat satu endpoint (`ess.inventory.set_tank_last_test`) begitu tanggalnya
// diubah, bukan menitipkannya ke autosave order.
//
// Uji berkala yang dikerjakan di depo sendiri mengisi field ini otomatis saat M&R-nya
// selesai (RepairOrder._stamp_last_test_date). Yang diketik di sini adalah uji yang terjadi
// di luar: di vendor, di depo lain, atau sebelum tank ini pernah masuk ke sini — satu-satunya
// jalan agar riwayat tank tidak terputus di pagar depo.
import { ref } from "vue"

import { send } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"

const props = defineProps({
	container: { type: String, default: "" }, // nama Container; kosong = tampil saja
	modelValue: { type: String, default: "" }, // ISO date dari master
})
const emit = defineEmits(["update:modelValue"])

const id = `last-test-${Math.random().toString(36).slice(2)}`
const saving = ref(false)
const today = new Date().toISOString().slice(0, 10)

async function save(input) {
	// Mengosongkan tidak lewat sini (lihat container.set_last_test_date) — kembalikan saja.
	if (!input.value) {
		input.value = String(props.modelValue || "").slice(0, 10)
		return
	}
	saving.value = true
	try {
		const r = await send({
			url: "container_depot.ess.inventory.set_tank_last_test",
			payload: { container: props.container, last_test_date: input.value },
		})
		// Server yang menentukan nilai akhirnya (ia yang menormalkan tanggalnya).
		emit("update:modelValue", r?.message?.last_test_date || input.value)
		toast.success(labels.lastTestSaved)
	} catch (e) {
		input.value = String(props.modelValue || "").slice(0, 10)
		toast.error(e?.message || String(e))
	} finally {
		saving.value = false
	}
}
</script>
