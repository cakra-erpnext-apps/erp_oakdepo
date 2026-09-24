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
					<button class="oak-press text-sm font-bold text-brand-600" @click="Object.assign(draft, empty)">
						{{ labels.monitorFilterReset }}
					</button>
				</div>

				<template v-for="fl in fields" :key="fl.key">
					<!-- Pilihan tunggal selebar layar (mis. Semua / Aktif saja); judul opsional. -->
					<div v-if="fl.type === 'scope'" class="space-y-1.5">
						<p v-if="fl.label" class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ fl.label }}</p>
						<div class="grid gap-1.5" :style="{ gridTemplateColumns: `repeat(${fl.choices.length}, minmax(0, 1fr))` }">
							<button
								v-for="o in fl.choices"
								:key="String(o.key)"
								class="oak-press min-h-[44px] rounded-xl border px-2 text-sm font-bold transition"
								:class="draft[fl.key] === o.key ? on : off"
								@click="draft[fl.key] = o.key"
							>
								{{ o.label }}
							</button>
						</div>
					</div>

					<button
						v-else-if="fl.type === 'toggle'"
						class="oak-press flex min-h-[44px] w-full items-center justify-between gap-2 rounded-xl border px-3 text-sm font-bold transition"
						:class="draft[fl.key] ? on : off"
						:aria-pressed="!!draft[fl.key]"
						@click="draft[fl.key] = !draft[fl.key]"
					>
						<span class="flex items-center gap-2"><Icon v-if="fl.icon" :name="fl.icon" :size="16" /> {{ fl.label }}</span>
						<Icon :name="draft[fl.key] ? 'check-square' : 'square'" :size="18" />
					</button>

					<div v-else-if="fl.type === 'date'" class="space-y-1.5">
						<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ fl.label }}</p>
						<div class="flex items-center gap-2">
							<input v-model="draft[fl.key]" type="date" class="oak-input min-h-[44px] min-w-0 flex-1" />
							<!-- Pintasan "Hari ini": saringan paling sering, tanpa membuka kalender. -->
							<button
								class="oak-press min-h-[44px] shrink-0 rounded-xl border px-3 text-xs font-bold transition"
								:class="draft[fl.key] === todayIso() ? on : off"
								@click="draft[fl.key] = todayIso()"
							>
								{{ labels.filterToday }}
							</button>
							<button v-if="draft[fl.key]" class="oak-press shrink-0 px-2 text-xs font-bold text-gray-500" @click="draft[fl.key] = ''">
								{{ labels.monitorAll }}
							</button>
						</div>
					</div>

					<!-- Sedikit pilihan (mis. depo): chip. -->
					<div v-else-if="fl.type === 'chips' && (options[fl.list] || []).length > 1" class="space-y-1.5">
						<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ fl.label }}</p>
						<div class="flex flex-wrap gap-1.5">
							<button
								v-for="d in ['', ...options[fl.list]]"
								:key="d || 'all'"
								class="oak-press min-h-[38px] rounded-full border px-3 text-xs font-bold transition"
								:class="draft[fl.key] === d ? on : off"
								@click="draft[fl.key] = d"
							>
								{{ d || labels.monitorAll }}
								<span v-if="countOf(fl.key, d) != null" class="ml-1 font-semibold opacity-60">{{ countOf(fl.key, d) }}</span>
							</button>
						</div>
					</div>

					<!-- Banyak pilihan (mis. nama PT): dropdown yang bisa dicari. -->
					<div v-else-if="fl.type === 'select' && (options[fl.list] || []).length" class="space-y-1.5">
						<p class="text-xs font-bold uppercase tracking-wide text-gray-400">{{ fl.label }}</p>
						<SearchSelect
							v-model="draft[fl.key]"
							:options="options[fl.list]"
							:option-label="counts[fl.key] ? (o) => withCount(fl.key, o) : null"
							:placeholder="labels.monitorAll"
							:clear-label="labels.monitorAll"
							trigger-class="min-h-[44px]"
						/>
					</div>
				</template>
			</div>

			<!-- Kaki menempel: sheet bisa lebih panjang dari layar HP kecil. -->
			<div class="sticky bottom-0 flex gap-2 border-t border-gray-100 bg-paper px-4 pb-4 pt-3">
				<button class="oak-btn oak-btn-secondary min-h-[48px] flex-1" @click="close">
					{{ labels.monitorCancel }}
				</button>
				<button class="oak-btn oak-btn-primary min-h-[48px] flex-[2]" @click="apply">
					{{ labels.monitorApply }}
					<span v-if="preview != null" class="font-normal opacity-90">· {{ preview }} {{ previewUnit }}</span>
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
import Icon from "@/components/Icon.vue"

const props = defineProps({
	open: { type: Boolean, default: false },
	// Filter yang SEDANG berlaku — titik awal draft tiap kali sheet dibuka.
	value: { type: Object, required: true },
	options: { type: Object, default: () => ({}) },
	// [{ key, type: scope|toggle|date|chips|select, label, list?, choices?, icon?, empty? }]
	fields: { type: Array, required: true },
	// Opsional — angka di balik tiap pilihan untuk DRAFT saat ini: { [fieldKey]: { [value]: n } }
	// (key "" = Semua). Halaman mengisinya dari event `draft`.
	counts: { type: Object, default: () => ({}) },
	// Opsional — isi daftar kalau draft ini diterapkan (angka di tombol Terapkan).
	preview: { type: Number, default: null },
	previewUnit: { type: String, default: "" },
})
const emit = defineEmits(["close", "apply", "draft"])

function countOf(key, value) {
	return props.counts?.[key]?.[value]
}
function withCount(key, o) {
	const value = typeof o === "object" ? o.value : o
	const label = typeof o === "object" ? o.label : o
	const n = countOf(key, value)
	return n == null ? label : `${label} (${n})`
}

// Tanggal lokal HP (YYYY-MM-DD), bukan toISOString() yang UTC — jam 00–07 WIB jadi kemarin.
const todayIso = () => new Date().toLocaleDateString("sv-SE")

const on = "border-brand-500 bg-brand-500/10 text-brand-700"
const off = "border-gray-200 bg-paper text-gray-600"
const empty = computed(() =>
	Object.fromEntries(props.fields.map((fl) => [fl.key, "empty" in fl ? fl.empty : fl.type === "toggle" ? false : ""]))
)

const draft = reactive({})
watch(
	() => props.open,
	(v) => v && Object.assign(draft, empty.value, props.value),
	{ immediate: true }
)

// Draft yang berubah selagi sheet terbuka — halaman boleh menghitung ulang `counts`/`preview`.
watch(draft, () => props.open && emit("draft", { ...draft }), { deep: true })

function close() {
	emit("close")
}
useDismissOnBack(
	computed(() => props.open),
	close
)
function apply() {
	// SearchSelect mengosongkan jadi null; server dan chip memakai "".
	emit("apply", Object.fromEntries(Object.keys(empty.value).map((k) => [k, draft[k] ?? ""])))
	close()
}
</script>
