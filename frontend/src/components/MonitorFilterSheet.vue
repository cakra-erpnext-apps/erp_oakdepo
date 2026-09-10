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
					<!-- Reset mengosongkan DRAFT, bukan filter yang sedang berlaku: sheet ini
					     belum mengubah apa pun sampai Terapkan ditekan, dan tombol yang diam-diam
					     bekerja lebih awal dari tombol utamanya adalah tombol yang menipu. -->
					<button class="oak-press text-sm font-bold text-brand-600" @click="resetDraft">
						{{ labels.monitorFilterReset }}
					</button>
				</div>

				<!-- Depot -->
				<div v-if="depots.length > 1" class="space-y-1.5">
					<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.monitorFilterDepot }}</p>
					<div class="flex flex-wrap gap-1.5">
						<FacetChip :active="!draft.depot" :label="labels.monitorAll" :count="facets?.all" @pick="draft.depot = ''" />
						<FacetChip
							v-for="d in depots"
							:key="d.code"
							:active="draft.depot === d.code"
							:label="d.code"
							:count="countOf(facets?.depots, 'code', d.code)"
							@pick="draft.depot = d.code"
						/>
					</div>
				</div>

				<!-- Prinsipal = customer pemilik tank -->
				<div v-if="principals.length" class="space-y-1.5">
					<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.monitorFilterPrincipal }}</p>
					<div class="flex flex-wrap gap-1.5">
						<FacetChip :active="!draft.principal" :label="labels.monitorAll" @pick="draft.principal = ''" />
						<FacetChip
							v-for="p in principals"
							:key="p.name"
							:active="draft.principal === p.name"
							:label="p.label"
							:count="countOf(facets?.principals, 'name', p.name)"
							@pick="draft.principal = p.name"
						/>
					</div>
				</div>

				<!-- Periode aktivitas -->
				<div class="space-y-1.5">
					<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.monitorFilterPeriod }}</p>
					<div class="grid grid-cols-3 gap-1.5">
						<OptionButton
							v-for="p in PERIODS"
							:key="p.key"
							:active="draft.period === p.key"
							:label="p.label"
							@pick="draft.period = p.key"
						/>
					</div>
				</div>

				<!-- Urutkan -->
				<div class="space-y-1.5">
					<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.monitorFilterSort }}</p>
					<div class="grid grid-cols-3 gap-1.5">
						<OptionButton
							v-for="o in SORTS"
							:key="o.key"
							:active="draft.sort === o.key"
							:label="o.label"
							@pick="draft.sort = o.key"
						/>
					</div>
				</div>
			</div>

			<!-- Kaki menempel: sheet ini bisa lebih panjang dari layar HP kecil, dan tombol
			     Terapkan yang ikut tergulung ke bawah lipatan adalah tombol yang tidak ketemu. -->
			<div class="sticky bottom-0 flex gap-2 border-t border-gray-100 bg-paper px-4 pb-4 pt-3">
				<button class="oak-btn oak-btn-secondary min-h-[48px] flex-1" @click="close">
					{{ labels.monitorCancel }}
				</button>
				<button class="oak-btn oak-btn-primary min-h-[48px] flex-[2]" @click="apply">
					{{ labels.monitorApply }}
					<!-- Angkanya adalah janji: sekian tank yang akan muncul di daftar setelah
					     tombol ini ditekan. Selagi hitungannya belum mendarat, tidak ada angka
					     yang ditampilkan — angka basi lebih buruk daripada tidak ada angka. -->
					<span v-if="!loading && facets" class="font-normal opacity-90">· {{ facets.total }} {{ labels.monitorTankWord }}</span>
				</button>
			</div>
		</section>
	</teleport>
</template>

<script setup>
import { computed, h, reactive, watch } from "vue"
import { labels } from "@/utils/labels"
import { useDismissOnBack } from "@/utils/backstack"

const props = defineProps({
	open: { type: Boolean, default: false },
	// Filter yang SEDANG berlaku di halaman — titik awal draft tiap kali sheet dibuka.
	value: { type: Object, required: true },
	depots: { type: Array, default: () => [] },
	principals: { type: Array, default: () => [] },
	// { total, all, depots:[{code,count}], principals:[{name,count}] } untuk draft saat ini.
	facets: { type: Object, default: null },
	loading: { type: Boolean, default: false },
})
const emit = defineEmits(["close", "apply", "draft"])

const PERIODS = [
	{ key: "today", label: labels.monitorPeriodToday },
	{ key: "7d", label: labels.monitorPeriod7 },
	{ key: "all", label: labels.monitorPeriodAll },
]
const SORTS = [
	{ key: "activity", label: labels.monitorSortActivity },
	{ key: "number", label: labels.monitorSortNumber },
	{ key: "idle", label: labels.monitorSortIdle },
]

const draft = reactive({ depot: "", principal: "", period: "all", sort: "activity" })

function seed() {
	Object.assign(draft, {
		depot: props.value.depot || "",
		principal: props.value.principal || "",
		period: props.value.period || "all",
		sort: props.value.sort || "activity",
	})
}
function resetDraft() {
	Object.assign(draft, { depot: "", principal: "", period: "all", sort: "activity" })
}

// Dibuka = mulai dari filter yang berlaku. Tanpa ini sheet mengingat coretan yang dibatalkan
// sesi sebelumnya dan menyodorkannya lagi seolah-olah itu yang sedang berlaku.
watch(
	() => props.open,
	(v) => v && seed(),
	{ immediate: true }
)
// Tiap perubahan draft meminta hitungan baru ke induknya (yang men-debounce-nya).
watch(draft, () => props.open && emit("draft", { ...draft }), { deep: true })

function close() {
	emit("close")
}
useDismissOnBack(
	computed(() => props.open),
	close
)
function apply() {
	emit("apply", { ...draft })
	close()
}

function countOf(list, key, value) {
	return (list || []).find((r) => r[key] === value)?.count
}

// Dua tombol kecil yang dipakai berulang di atas. Ditulis sebagai render function di file
// yang sama, bukan komponen tersendiri: keduanya cuma bentuk tombol dan tidak punya arti di
// luar sheet ini — file terpisah hanya akan memindahkan tempat mencarinya.
const FacetChip = (p, { emit: e }) =>
	h(
		"button",
		{
			class: [
				"oak-press flex min-h-[38px] items-center gap-1.5 rounded-full border px-3 text-xs font-bold transition",
				p.active
					? "border-brand-500 bg-brand-500/10 text-brand-700"
					: "border-gray-200 bg-paper text-gray-600",
			],
			onClick: () => e("pick"),
		},
		[
			h("span", { class: "truncate" }, p.label),
			p.count === undefined || p.count === null
				? null
				: h(
						"span",
						{
							class: [
								"rounded-full px-1.5 py-0.5 text-[10px] font-extrabold",
								p.active ? "bg-brand-500/20 text-brand-700" : "bg-gray-100 text-gray-500",
							],
						},
						String(p.count)
					),
		]
	)
FacetChip.props = ["active", "label", "count"]
FacetChip.emits = ["pick"]

const OptionButton = (p, { emit: e }) =>
	h(
		"button",
		{
			class: [
				"oak-press min-h-[48px] rounded-xl border px-2 text-sm font-bold transition",
				p.active
					? "border-brand-500 bg-brand-500/10 text-brand-700"
					: "border-gray-200 bg-paper text-gray-600",
			],
			onClick: () => e("pick"),
		},
		p.label
	)
OptionButton.props = ["active", "label"]
OptionButton.emits = ["pick"]
</script>
