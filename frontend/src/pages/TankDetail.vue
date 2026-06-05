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

			<!-- F3 — repair tracking & estimate -->
			<section>
				<h2 class="mb-2 text-sm font-semibold text-gray-700">{{ labels.repairs }}</h2>
				<p v-if="repairs.loading && !repairs.data" class="text-sm text-gray-500">
					{{ labels.loading }}
				</p>
				<p v-else-if="repairs.error" class="text-sm text-red-600">
					{{ labels.error }}
					<button class="underline" @click="repairs.reload()">{{ labels.retry }}</button>
				</p>
				<p v-else-if="!repairList.length" class="text-sm text-gray-500">
					{{ labels.noRepairs }}
				</p>
				<ul v-else class="space-y-2">
					<li
						v-for="ro in repairList"
						:key="ro.name"
						class="rounded-lg border bg-white p-3"
					>
						<div class="flex items-center justify-between gap-2">
							<span class="text-sm font-medium">{{ ro.repair_order_id || ro.name }}</span>
							<span class="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
								{{ repairStatusLabel(ro.status) }}
							</span>
						</div>
						<div class="mt-1 flex justify-between text-xs text-gray-500">
							<span>{{ labels.billing }}: {{ billingLabel(ro.billing_status) }}</span>
							<span class="font-medium text-gray-900">
								{{ labels.estimateTotal }}: {{ rupiah(ro.total_cost) }}
							</span>
						</div>

						<ul v-if="ro.items.length" class="mt-2 divide-y border-t text-xs">
							<li v-for="(it, i) in ro.items" :key="i" class="flex justify-between gap-2 py-1">
								<span class="min-w-0 truncate text-gray-600">
									{{ it.part_description || "—" }}
								</span>
								<span class="shrink-0 text-gray-900">
									{{ rupiah((it.total_price || 0) + (it.labor_total || 0)) }}
								</span>
							</li>
						</ul>

						<div v-if="ro.next_statuses.length" class="mt-3 flex flex-wrap gap-2">
							<button
								v-for="ns in ro.next_statuses"
								:key="ns"
								class="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
								:disabled="repairAction.loading"
								@click="advance(ro.name, ns)"
							>
								→ {{ repairStatusLabel(ns) }}
							</button>
						</div>
						<p v-if="repairAction.error && actingOn === ro.name" class="mt-2 text-xs text-red-600">
							{{ repairActionError }}
						</p>
					</li>
				</ul>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource } from "frappe-ui"
import StatusChip from "@/components/StatusChip.vue"
import {
	labels,
	repairStatusLabel,
	billingLabel,
	rupiah,
} from "@/utils/labels"

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

const repairs = createResource({
	url: "container_depot.ess.repairs.get_tank_repairs",
	method: "GET",
	makeParams: () => ({ container: props.name }),
	auto: true,
})
const repairList = computed(() => repairs.data?.repairs || [])

// Approval action (POST). On success, refresh repairs + the detail card, since
// advancing a repair propagates the container's derived status server-side.
const actingOn = ref(null)
const repairAction = createResource({
	url: "container_depot.ess.repairs.set_repair_status",
	method: "POST",
	onSuccess() {
		repairs.reload()
		detail.reload()
	},
})
const repairActionError = computed(
	() => repairAction.error?.messages?.[0] || repairAction.error?.message || labels.error
)

function advance(repairOrder, status) {
	actingOn.value = repairOrder
	repairAction.submit({ repair_order: repairOrder, status })
}

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
