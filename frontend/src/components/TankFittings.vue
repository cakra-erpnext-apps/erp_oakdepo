<template>
	<section class="oak-card overflow-hidden">
		<div class="flex items-center justify-between gap-2 border-b border-gray-100 px-4 py-3">
			<div class="flex items-center gap-2">
				<Icon name="clipboard" :size="16" class="text-gray-400" />
				<p class="oak-section-title">{{ title }}</p>
			</div>
			<span v-if="rows.length" class="oak-chip" :class="filledCount ? 'bg-leaf-100 text-leaf-700' : 'bg-gray-100 text-gray-500'">
				{{ filledCount }}/{{ rows.length }}
			</span>
		</div>

		<p class="px-4 pt-3 text-xs text-gray-400">{{ hint }}</p>

		<div v-for="g in groups" :key="g.compartment" class="mt-3">
			<p class="bg-gray-50 px-4 py-1 text-[11px] font-bold uppercase tracking-wide text-gray-500">{{ g.compartment }}</p>
			<div v-for="it in g.items" :key="it.key" class="border-t border-gray-100 px-4 py-2.5">
				<p class="text-sm font-semibold text-gray-700">{{ it.item_label }}</p>
				<div class="mt-1.5 grid gap-2" :class="it.slots.length > 1 ? 'grid-cols-2' : 'grid-cols-1'">
					<div v-for="r in it.slots" :key="r.fitting_item" class="min-w-0 space-y-1">
						<label class="flex items-baseline gap-1 text-[11px] font-medium text-gray-500">
							<span>{{ r.slot_label || labels.fittingValue }}</span>
							<span v-if="r.uom" class="text-gray-400">({{ r.uom }})</span>
						</label>

						<!-- Choice: the printed form offers a short list AND an "Other ..." write-in,
						     so the select falls back to a free-text box instead of forcing a match. -->
						<select
							v-if="isChoice(r) && !r.otherMode"
							:value="r.value"
							class="oak-input px-2.5 py-2 text-sm"
							@change="pickChoice(r, $event.target.value)"
						>
							<option value="">—</option>
							<option v-for="o in r.options" :key="o" :value="o">{{ o }}</option>
							<option value="__other__">{{ labels.fittingOther }}</option>
						</select>
						<template v-else-if="isChoice(r)">
							<input
								v-model.trim="r.value"
								type="text"
								:placeholder="labels.fittingOtherPlaceholder"
								class="oak-input px-2.5 py-2 text-sm"
							/>
							<button type="button" class="text-[10px] font-semibold text-brand-600" @click="leaveOther(r)">
								{{ labels.fittingBackToList }}
							</button>
						</template>

						<input
							v-else
							v-model.trim="r.value"
							type="number"
							inputmode="decimal"
							step="any"
							min="0"
							class="oak-input px-2.5 py-2 text-sm"
						/>

						<p
							v-if="showBaseline && r.baseline"
							class="text-[10px]"
							:class="changed(r) ? 'font-bold text-amber-600' : 'text-gray-400'"
						>
							{{ labels.fittingBaseline }} {{ r.baseline }}{{ r.uom ? " " + r.uom : "" }}
						</p>
					</div>
				</div>
			</div>
		</div>
	</section>
</template>

<script setup>
// Kelengkapan tank — the fill-in boxes on the printed EIR sheet (steam pipe bore, manlid
// seal type, how many straps). NOT defects: the damage checklist next door answers "what
// is broken", this answers "what is fitted, and how much". Recorded at BOTH gates so a
// strap that came in and did not leave shows up as a difference rather than a memory.
//
// Operates on the parent's reactive `rows` array in place — one row per master slot,
// already merged with the draft's saved values — so the parent's autosave watcher and
// buildFittings() keep working unchanged.
import { computed } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	rows: { type: Array, required: true },
	title: { type: String, default: labels.fittingsTitle },
	hint: { type: String, default: labels.fittingsHint },
	// EIR-Out shows what the same slot held at EIR-In beside each box.
	showBaseline: { type: Boolean, default: false },
})

const isChoice = (r) => r.value_type === "Choice"
const changed = (r) => String(r.value || "").trim() !== String(r.baseline || "").trim()

const filledCount = computed(() => props.rows.filter((r) => String(r.value ?? "").trim()).length)

// compartment -> item -> its input boxes, in the master's printed order.
const groups = computed(() => {
	const out = []
	const byCompartment = new Map()
	for (const r of props.rows) {
		let g = byCompartment.get(r.compartment)
		if (!g) {
			g = { compartment: r.compartment, items: [], byItem: new Map() }
			byCompartment.set(r.compartment, g)
			out.push(g)
		}
		const key = `${r.compartment}|${r.item_label}`
		let it = g.byItem.get(key)
		if (!it) {
			it = { key, item_label: r.item_label, slots: [] }
			g.byItem.set(key, it)
			g.items.push(it)
		}
		it.slots.push(r)
	}
	return out
})

function pickChoice(row, picked) {
	if (picked === "__other__") {
		row.otherMode = true
		row.value = ""
		return
	}
	row.value = picked
}

function leaveOther(row) {
	row.otherMode = false
	row.value = ""
}
</script>
