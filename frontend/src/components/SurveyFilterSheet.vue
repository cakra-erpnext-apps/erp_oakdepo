<template>
	<teleport to="body">
		<div
			v-if="open"
			class="fixed inset-0 z-40 animate-fade-in bg-gray-900/40 backdrop-blur-[1px]"
			@click="close"
		></div>
		<section
			v-if="open"
			class="fixed inset-x-0 bottom-0 z-50 max-h-[86vh] animate-slide-up overflow-y-auto rounded-t-3xl bg-paper pb-safe-bottom shadow-soft"
			role="dialog"
			aria-modal="true"
		>
			<button class="w-full pb-1 pt-2.5" :aria-label="labels.moreClose" @click="close">
				<span class="mx-auto block h-1 w-10 rounded-full bg-gray-300"></span>
			</button>

			<div class="space-y-4 px-4 pb-4 pt-1">
				<div class="flex items-baseline justify-between gap-3">
					<h2 class="text-base font-extrabold leading-tight text-gray-900">{{ labels.monitorFilterTitle }}</h2>
					<!-- Reset mengosongkan DRAFT saja — belum ada yang berubah sampai Terapkan. -->
					<button class="oak-press text-sm font-bold text-brand-600" @click="Object.assign(draft, EMPTY)">
						{{ labels.monitorFilterReset }}
					</button>
				</div>

				<!-- Tampilkan: semua atau yang masih jalan saja -->
				<div class="grid grid-cols-2 gap-1.5">
					<button
						v-for="o in SCOPES"
						:key="o.key"
						class="oak-press min-h-[44px] rounded-xl border px-2 text-sm font-bold transition"
						:class="draft.activeOnly === o.key ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
						@click="draft.activeOnly = o.key"
					>
						{{ o.label }}
					</button>
				</div>

				<div class="space-y-1.5">
					<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.svChipDate }}</p>
					<div class="flex items-center gap-2">
						<input v-model="draft.day" type="date" class="oak-input min-h-[44px] flex-1" />
						<button v-if="draft.day" class="oak-press shrink-0 px-2 text-xs font-bold text-gray-500" @click="draft.day = ''">
							{{ labels.monitorAll }}
						</button>
					</div>
				</div>

				<!-- Depo: sedikit, jadi chip. -->
				<div v-if="options.depots.length > 1" class="space-y-1.5">
					<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.svChipDepot }}</p>
					<div class="flex flex-wrap gap-1.5">
						<button
							v-for="d in ['', ...options.depots]"
							:key="d || 'all'"
							class="oak-press min-h-[38px] rounded-full border px-3 text-xs font-bold transition"
							:class="draft.depot === d ? 'border-brand-500 bg-brand-500/10 text-brand-700' : 'border-gray-200 bg-paper text-gray-600'"
							@click="draft.depot = d"
						>
							{{ d || labels.monitorAll }}
						</button>
					</div>
				</div>

				<!-- Pihak-pihak: bisa puluhan nama, jadi dropdown yang bisa dicari — bukan chip. -->
				<div v-for="p in PARTIES" :key="p.key" v-show="options[p.list].length" class="space-y-1.5">
					<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ p.label }}</p>
					<SearchSelect
						v-model="draft[p.key]"
						:options="options[p.list]"
						:placeholder="labels.monitorAll"
						:clear-label="labels.monitorAll"
						trigger-class="min-h-[44px]"
					/>
				</div>
			</div>

			<!-- Kaki menempel: sheet bisa lebih panjang dari layar HP kecil. -->
			<div class="sticky bottom-0 flex gap-2 border-t border-gray-100 bg-paper px-4 pb-4 pt-3">
				<button class="oak-btn oak-btn-secondary min-h-[48px] flex-1" @click="close">
					{{ labels.monitorCancel }}
				</button>
				<button class="oak-btn oak-btn-primary min-h-[48px] flex-[2]" @click="apply">
					{{ labels.monitorApply }}
				</button>
			</div>
		</section>
	</teleport>
</template>

<script setup>
import { computed, reactive, watch } from "vue"
import { labels } from "@/utils/labels"
import { useDismissOnBack } from "@/utils/backstack"
import SearchSelect from "@/components/SearchSelect.vue"

const props = defineProps({
	open: { type: Boolean, default: false },
	// Filter yang SEDANG berlaku — titik awal draft tiap kali sheet dibuka.
	value: { type: Object, required: true },
	options: { type: Object, required: true },
})
const emit = defineEmits(["close", "apply"])

const EMPTY = { day: "", depot: "", principal: "", surveyor: "", shipper: "", emkl: "", activeOnly: false }
const SCOPES = [
	{ key: false, label: labels.monitorAll },
	{ key: true, label: labels.svChipActive },
]
const PARTIES = [
	{ key: "principal", list: "principals", label: labels.svChipPrincipal },
	{ key: "surveyor", list: "surveyors", label: labels.svSurveyor },
	{ key: "shipper", list: "shippers", label: labels.shipper },
	{ key: "emkl", list: "emkls", label: labels.svEmkl },
]

const draft = reactive({ ...EMPTY })
watch(
	() => props.open,
	(v) => v && Object.assign(draft, EMPTY, props.value),
	{ immediate: true }
)

function close() {
	emit("close")
}
useDismissOnBack(
	computed(() => props.open),
	close
)
function apply() {
	// SearchSelect mengosongkan jadi null; server dan chip memakai "".
	emit("apply", Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, v ?? ""])))
	close()
}
</script>
