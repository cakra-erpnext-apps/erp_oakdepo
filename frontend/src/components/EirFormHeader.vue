<template>
	<!-- Header form EIR: tank yang sedang diperiksa, lamanya sudah berjalan, dan langkah ke
	     berapa dari berapa. Menempel di bawah bar batch (kalau ada) lewat
	     .oak-subheader-stacked — dua bar, dua tinggi, tidak pernah saling menimpa. -->
	<div class="oak-subheader-stacked -mx-4 space-y-2 border-b border-gray-200/80 bg-gray-50/95 px-4 py-2 backdrop-blur">
		<div class="flex items-center gap-2">
			<button class="oak-btn oak-btn-secondary px-2 py-2" :aria-label="labels.backBtn" @click="emit('back')">
				<Icon name="arrow-left" :size="18" />
			</button>
			<div class="min-w-0 flex-1">
				<h2 class="truncate text-base font-extrabold leading-tight tracking-tight">{{ title }}</h2>
				<p v-if="subtitle" class="truncate text-[11px] leading-tight text-gray-500">{{ subtitle }}</p>
			</div>
			<!-- Penghitung waktu, bukan cap waktu mulai: yang ditanya operator di tengah
			     pemeriksaan adalah "sudah berapa lama", dan jam mulai memaksa mereka
			     menghitungnya sendiri. Hilang begitu EIR belum dimulai — di situ chip-nya
			     mengatakan hal yang lebih berguna. -->
			<span v-if="elapsed" class="oak-chip shrink-0 bg-blue-100 font-mono text-blue-700">{{ elapsed }}</span>
			<span v-else-if="!startedMs" class="oak-chip shrink-0 bg-gray-100 text-gray-500">{{ labels.eirBatchNotStarted }}</span>
		</div>

		<template v-if="steps.length">
			<div class="flex items-center gap-1">
				<span
					v-for="(s, i) in steps"
					:key="s"
					class="h-1 flex-1 rounded-full transition-colors"
					:class="i < step ? 'bg-leaf-500' : i === step ? 'bg-brand-500' : 'bg-gray-200'"
				></span>
			</div>
			<div class="flex items-baseline justify-between gap-2 text-[11px]">
				<p class="min-w-0 truncate font-semibold text-gray-700">
					{{ step + 1 }} · {{ steps[step] }}
					<span class="font-normal text-gray-400">{{ labels.eirBatchOf }} {{ steps.length }}</span>
				</p>
				<p class="shrink-0 text-gray-400">{{ status }}</p>
			</div>
		</template>
	</div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	title: { type: String, default: "" },
	subtitle: { type: String, default: "" },
	// Nama langkah, urut. Kosong = form belum masuk mode langkah (mis. layar Mulai).
	steps: { type: Array, default: () => [] },
	step: { type: Number, default: 0 },
	// Titik nol penghitung waktu (ms). 0 = belum dimulai.
	startedMs: { type: Number, default: 0 },
	status: { type: String, default: "" },
})
const emit = defineEmits(["back"])

// mm:ss sampai satu jam, lalu h:mm:ss — sebuah EIR yang berjalan 90 menit tidak boleh
// dicetak sebagai "90:12" (dibaca sebagai jam oleh siapa pun yang melirik).
const elapsed = ref("")
let timer = null
function tick() {
	if (!props.startedMs) {
		elapsed.value = ""
		return
	}
	const secs = Math.floor((Date.now() - props.startedMs) / 1000)
	// Jam HP di depan jam server (atau EIR yang tertinggal sejak kemarin): angka yang tidak
	// masuk akal lebih buruk daripada tidak ada angka.
	if (secs < 0 || secs > 24 * 3600) {
		elapsed.value = ""
		return
	}
	const s = String(secs % 60).padStart(2, "0")
	const m = Math.floor(secs / 60) % 60
	const h = Math.floor(secs / 3600)
	elapsed.value = h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${String(m).padStart(2, "0")}:${s}`
}
watch(
	() => props.startedMs,
	() => {
		tick()
		if (!timer) timer = setInterval(tick, 1000)
	},
	{ immediate: true }
)
onBeforeUnmount(() => clearInterval(timer))
</script>
