<template>
	<div class="mx-auto w-full max-w-lg space-y-4">
		<router-link to="/tanks" class="text-sm text-gray-500 hover:text-gray-900">
			← {{ labels.inventory }}
		</router-link>

		<p v-if="detail.loading && !detail.data" class="text-sm text-gray-500">
			{{ labels.loading }}
		</p>
		<p v-else-if="detail.error" class="text-sm text-red-600">
			{{ labels.error }}
			<button class="underline" @click="detail.reload()">{{ labels.retry }}</button>
		</p>

		<template v-else-if="detail.data">
			<header class="rounded-lg border bg-white p-4">
				<div class="flex items-start justify-between gap-3">
					<h1 class="text-lg font-semibold">{{ detail.data.container_no }}</h1>
					<StatusChip :bucket="detail.data.status" />
				</div>
				<p
					v-if="detail.data.pt_due"
					class="mt-2 inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
				>
					{{ labels.ptDue }}
				</p>
			</header>

			<dl class="divide-y rounded-lg border bg-white">
				<div
					v-for="row in rows"
					:key="row.label"
					class="flex justify-between gap-4 px-4 py-2.5"
				>
					<dt class="text-sm text-gray-500">{{ row.label }}</dt>
					<dd class="text-right text-sm font-medium">{{ row.value }}</dd>
				</div>
			</dl>

			<!-- F2 — documents (EIR, cleaning cert, repair estimate, bon) -->
			<section>
				<h2 class="mb-2 text-sm font-semibold text-gray-700">{{ labels.documents }}</h2>
				<p v-if="documents.loading && !documents.data" class="text-sm text-gray-500">
					{{ labels.loading }}
				</p>
				<p v-else-if="documents.error" class="text-sm text-red-600">
					{{ labels.error }}
					<button class="underline" @click="documents.reload()">{{ labels.retry }}</button>
				</p>
				<p v-else-if="!docs.length" class="text-sm text-gray-500">{{ labels.noDocuments }}</p>
				<ul v-else class="divide-y rounded-lg border bg-white">
					<li v-for="d in docs" :key="d.doctype + d.name">
						<a
							:href="d.view_url"
							target="_blank"
							rel="noopener"
							class="flex items-center justify-between gap-3 px-3 py-3 hover:bg-gray-50"
						>
							<div class="min-w-0">
								<p class="truncate text-sm font-medium">{{ d.label }}</p>
								<p class="text-xs text-gray-500">
									{{ d.category }}<span v-if="d.date"> · {{ d.date }}</span>
								</p>
							</div>
							<span class="shrink-0 text-xs font-medium text-blue-600">
								{{ labels.viewPrint }} ↗
							</span>
						</a>
					</li>
				</ul>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { createResource } from "frappe-ui"
import StatusChip from "@/components/StatusChip.vue"
import { labels } from "@/utils/labels"

const props = defineProps({
	name: { type: String, required: true },
})

const detail = createResource({
	url: "container_depot.ess.inventory.get_tank_detail",
	method: "GET",
	makeParams: () => ({ container: props.name }),
	auto: true,
})

const documents = createResource({
	url: "container_depot.ess.documents.get_tank_documents",
	method: "GET",
	makeParams: () => ({ container: props.name }),
	auto: true,
})

const docs = computed(() => documents.data?.documents || [])

function fmtNum(v, unit) {
	if (v === null || v === undefined || v === "" || Number(v) === 0) return null
	const n = Number(v).toLocaleString("id-ID")
	return unit ? `${n} ${unit}` : n
}

// Only rows with a value are shown, so the card stays compact on a phone.
const rows = computed(() => {
	const d = detail.data
	if (!d) return []
	const zone = d.yard_zone ? d.yard_zone.replace(/_/g, " ") : null
	const all = [
		{ label: labels.type, value: [d.container_type, d.size].filter(Boolean).join(" · ") },
		{ label: labels.capacity, value: fmtNum(d.capacity, "L") },
		{ label: labels.tare, value: fmtNum(d.tare_weight) },
		{ label: labels.maxGross, value: fmtNum(d.max_gross_weight) },
		{ label: labels.lastCargo, value: d.last_cargo },
		{ label: labels.lastTest, value: d.last_test_date },
		{ label: labels.ptDue, value: d.next_pt_due },
		{ label: labels.location, value: [zone, d.current_location].filter(Boolean).join(" · ") },
	]
	return all.filter((r) => r.value)
})
</script>
