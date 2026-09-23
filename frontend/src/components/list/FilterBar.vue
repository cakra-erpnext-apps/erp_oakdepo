<template>
	<!-- Filter: dua tombol selebar layar, bukan deretan chip yang lari ke kanan. Semua saringan
	     tinggal di satu sheet; yang aktif tampil di bawahnya sebagai chip yang turun baris
	     (wrap) — terlihat semua tanpa digeser, dan tiap chip bisa di-×. -->
	<div class="grid grid-cols-2 gap-2">
		<button
			class="oak-press flex min-h-[44px] items-center justify-center gap-2 rounded-xl border px-3 text-sm font-bold transition"
			:class="chips.length ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-700'"
			@click="emit('open')"
		>
			<Icon name="sliders" :size="15" /> {{ labels.monitorFilterTitle }}
			<span v-if="chips.length" class="rounded-full bg-brand-500 px-1.5 text-[11px] font-extrabold text-white">
				{{ chips.length }}
			</span>
		</button>
		<button
			class="oak-press flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-gray-200 bg-paper px-3 text-sm font-bold text-gray-700"
			@click="emit('sort')"
		>
			<Icon name="arrow-down" :size="15" /> {{ sortLabel }}
		</button>
	</div>

	<div v-if="chips.length || showClear" class="flex flex-wrap gap-1.5">
		<button
			v-for="c in chips"
			:key="c.key"
			class="oak-press flex min-h-[34px] max-w-full items-center gap-1 rounded-full border border-brand-500 bg-brand-500/10 pl-3 pr-2 text-xs font-bold text-brand-700"
			:aria-label="`${labels.monitorFilterReset} ${c.label}`"
			@click="emit('clear-one', c.key)"
		>
			<span class="truncate"><span class="font-semibold opacity-70">{{ c.label }}</span> {{ c.value }}</span>
			<Icon name="x" :size="13" class="shrink-0" />
		</button>
		<button class="oak-press min-h-[34px] rounded-full px-2 text-xs font-bold text-red-600" @click="emit('clear-all')">
			{{ labels.svClearAll }}
		</button>
	</div>
</template>

<script setup>
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

defineProps({
	chips: { type: Array, default: () => [] }, // [{ key, label, value }]
	sortLabel: { type: String, required: true },
	// "Hapus filter" juga saat hanya pencarian yang aktif.
	showClear: { type: Boolean, default: false },
})
const emit = defineEmits(["open", "sort", "clear-one", "clear-all"])
</script>
