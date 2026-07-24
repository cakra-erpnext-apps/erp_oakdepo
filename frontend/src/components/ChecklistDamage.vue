<template>
	<section class="oak-card overflow-hidden">
		<div class="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
			<div class="flex items-center gap-2">
				<Icon name="check-square" :size="16" class="text-gray-400" />
				<p class="oak-section-title">{{ title }}</p>
			</div>
			<span v-if="addedRows.length" class="oak-chip bg-amber-100 text-amber-700">{{ addedRows.length }}</span>
		</div>

		<!-- Search-to-add: only damaged parts are added; the rest are implicitly acceptable. -->
		<div class="border-b border-gray-100 px-4 py-2.5">
			<div class="relative">
				<span class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"><Icon name="search" :size="15" /></span>
				<input v-model.trim="query" type="text" :placeholder="labels.checklistSearchDamaged" class="oak-input pl-9 pr-9" />
				<button
					v-if="query"
					type="button"
					class="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
					:aria-label="labels.clear"
					@click="query = ''"
				>
					<Icon name="x" :size="15" />
				</button>
			</div>
			<!-- Live results while typing; pick one to add its fill-in card below. -->
			<div v-if="query" class="mt-2 overflow-hidden rounded-xl border border-gray-200">
				<p v-if="!pickerGroups.length" class="px-3 py-3 text-center text-sm text-gray-400">{{ labels.sectionSearchEmpty }}</p>
				<div v-for="g in pickerGroups" :key="g.area">
					<p class="bg-gray-50 px-3 py-1 text-[11px] font-bold uppercase tracking-wide text-gray-500">{{ g.area }}</p>
					<button
						v-for="item in g.items"
						:key="item.item_code"
						type="button"
						class="flex w-full items-center justify-between gap-2 border-t border-gray-100 px-3 py-2 text-left text-sm text-gray-700 hover:bg-brand-50"
						@click="addRow(item)"
					>
						<span class="truncate">{{ item.printed_no }}. {{ item.item_name }}</span>
						<Icon name="plus" :size="15" class="shrink-0 text-brand-500" />
					</button>
				</div>
			</div>
		</div>

		<!-- Added (damaged) parts — the same fill-in as before, one card each. -->
		<p v-if="!addedRows.length" class="px-4 py-6 text-center text-sm text-gray-400">{{ labels.checklistEmpty }}</p>
		<div v-for="r in addedRows" :key="r.item_code" class="border-b border-gray-100 px-4 py-3 last:border-b-0">
			<div class="flex items-start justify-between gap-2">
				<div class="min-w-0">
					<p class="text-sm font-semibold text-gray-800">{{ r.printed_no }}. {{ r.item_name }}</p>
					<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ r.area }}</p>
				</div>
				<button type="button" class="shrink-0 rounded-full bg-gray-100 p-1.5 text-gray-500 hover:bg-red-100 hover:text-red-600" @click="removeRow(r)">
					<Icon name="trash-2" :size="14" />
				</button>
			</div>
			<div class="mt-2 grid grid-cols-2 gap-2">
				<SearchSelect
					v-model="r.damage_code"
					:options="damageOptionsFor(r)"
					:option-value="(d) => d.code"
					:option-label="(d) => `${d.code} — ${d.description}`"
					:placeholder="labels.colDamage"
					:search-placeholder="labels.selectSearch"
					trigger-class="px-2.5 py-2"
				/>
				<SearchSelect
					v-model="r.repair_code"
					:options="repairOptionsFor(r)"
					:option-value="(r2) => r2.code"
					:option-label="(r2) => `${r2.code} — ${r2.description}`"
					:placeholder="labels.colRepair"
					:search-placeholder="labels.selectSearch"
					trigger-class="px-2.5 py-2"
				/>
			</div>
			<div class="mt-2 flex flex-wrap items-center gap-2">
				<div v-for="(url, idx) in r.photos" :key="url" class="relative">
					<button type="button" class="oak-press block" @click="openLightbox(r.photos, idx)">
						<img :src="url" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
					</button>
					<button type="button" class="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-gray-900 text-white shadow" @click="r.photos.splice(idx, 1)">
						<Icon name="x" :size="12" />
					</button>
				</div>
				<label class="flex h-16 w-16 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-lg border border-dashed border-gray-300 text-gray-400 transition hover:border-brand-400 hover:text-brand-500">
					<input type="file" accept="image/*" capture="environment" class="hidden" :disabled="r.uploading" @change="onPhotoPick(r, $event)" />
					<span v-if="r.uploading" class="text-xs">…</span>
					<template v-else><Icon name="camera" :size="18" /><span class="text-[9px] font-medium">{{ labels.photo }}</span></template>
				</label>
			</div>
			<p v-if="r.photoErr" class="mt-1 text-xs text-red-600">{{ r.photoErr }}</p>
			<!-- Note: intentionally blank for the user's own words — never pre-filled from the
			     damage/repair code (the server derives the stored description separately). -->
			<input v-model.trim="r.remarks" type="text" :placeholder="labels.colRemarksManual" class="oak-input mt-2 px-2.5 py-2" />
		</div>
	</section>
</template>

<script setup>
// Search-to-add inspection checklist. Instead of listing every part, the operator searches
// a section/part; picking one adds a fill-in card (damage/repair/photo/note). Only damaged
// parts are shown — acceptable parts stay implicit (the server skips blank rows).
//
// Operates on the parent's reactive `rows` array in place (each row is a reactive object),
// so the parent's existing buildLines()/buildPhotos()/applyDraftToRows() and autosave watcher
// keep working unchanged — we only flip `added` and edit fields on those same rows.
import { computed, ref } from "vue"
import { labels } from "@/utils/labels"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"
import SearchSelect from "@/components/SearchSelect.vue"

const ACCEPTABLE_DAMAGE = "v"
const NO_ACTION_REPAIR = "X"

const props = defineProps({
	rows: { type: Array, required: true }, // parent's reactive checklist rows (full list)
	damageCodes: { type: Array, default: () => [] },
	repairCodes: { type: Array, default: () => [] },
	upload: { type: Function, required: true }, // (File) => Promise<file_url>
	title: { type: String, default: labels.checklist },
})

const query = ref("")

const addedRows = computed(() => props.rows.filter((r) => r.added))

// Per-part code filtering: each checklist part carries the defect / repair codes that make
// sense for it (seeded from the EIR workbook onto Inspection Checklist Item). A part with no
// mapping falls back to the full list, and a value already saved on the row is always kept
// as an option so an existing EIR never loses its selection.
function narrow(all, allowed, current, key) {
	if (!allowed || !allowed.length) return all
	const keep = new Set(allowed)
	if (current) keep.add(current)
	// Preserve the mapping's order (primary repairs first), then anything extra.
	const byCode = new Map(all.map((o) => [o[key], o]))
	const out = []
	for (const code of allowed) if (byCode.has(code)) out.push(byCode.get(code))
	for (const o of all) if (keep.has(o[key]) && !out.includes(o)) out.push(o)
	return out
}
const damageOptionsFor = (r) => narrow(props.damageCodes, r.damage_codes, r.damage_code, "code")
const repairOptionsFor = (r) => narrow(props.repairCodes, r.repair_codes, r.repair_code, "code")

// Picker: items not yet added, grouped by area, matched on section name OR part text.
const pickerGroups = computed(() => {
	const q = query.value.trim().toLowerCase()
	const out = []
	let cur = null
	for (const r of props.rows) {
		if (r.added) continue
		if (q && !(`${r.area}`.toLowerCase().includes(q) || `${r.printed_no} ${r.item_name}`.toLowerCase().includes(q))) continue
		if (!cur || cur.area !== r.area) {
			cur = { area: r.area, items: [] }
			out.push(cur)
		}
		cur.items.push(r)
	}
	return out
})

function addRow(item) {
	item.added = true
	// Keep the query so several parts can be added from one search (each vanishes once added).
}

function removeRow(r) {
	r.added = false
	r.damage_code = ACCEPTABLE_DAMAGE
	r.repair_code = NO_ACTION_REPAIR
	r.remarks = ""
	r.photos = []
	r.photoErr = ""
}

async function onPhotoPick(item, event) {
	const files = Array.from(event.target.files || [])
	event.target.value = ""
	if (!files.length) return
	item.photoErr = ""
	item.uploading = true
	try {
		for (const f of files) item.photos.push(await props.upload(f))
	} catch (e) {
		item.photoErr = labels.photoError
	} finally {
		item.uploading = false
	}
}
</script>
