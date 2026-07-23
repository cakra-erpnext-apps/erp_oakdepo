<template>
	<HistoryPage
		:title="labels.eirHistoryTitle"
		icon="clipboard"
		back-to="/eir"
		:back-label="labels.eirTitle"
		list-url="container_depot.ess.inspections.eir_history"
		detail-url="container_depot.ess.inspections.eir_view"
		detail-param="inspection"
		:search-placeholder="labels.eirHistorySearch"
		:count-label="labels.eirHistoryCount"
	>
		<template #row="{ item }">
			<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="clipboard" :size="16" /></span>
			<div class="min-w-0 flex-1">
				<div class="flex items-center justify-between gap-2">
					<p class="truncate font-semibold text-gray-900">{{ item.container_no || item.container }}</p>
					<span class="oak-chip shrink-0" :class="statusClass(item)">{{ statusText(item) }}</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between gap-2 text-xs text-gray-500">
					<span class="truncate">{{ item.inspection_type }}<span v-if="item.tank_status"> · {{ item.tank_status }}</span></span>
					<span class="shrink-0">{{ fmtDate(item.eir_date || item.creation) }}</span>
				</div>
				<p class="truncate text-[11px] text-gray-400">{{ item.inspection_id || item.name }}</p>
			</div>
		</template>

		<template #detail="{ data }">
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="font-mono text-xs text-gray-400">{{ data.inspection_id || data.name }}</p>
						<h2 class="truncate text-lg font-extrabold text-gray-900">{{ data.container_no }}</h2>
					</div>
					<span class="oak-chip shrink-0" :class="statusClass(data)">{{ statusText(data) }}</span>
				</div>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="c in cells(data)" :key="c.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
				<p v-if="data.remarks" class="rounded-lg bg-gray-50 p-2 text-xs text-gray-600">{{ data.remarks }}</p>
			</section>

			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.eirDamages }} ({{ data.damage_count || 0 }})</p>
				<p v-if="!(data.damages || []).length" class="text-sm text-gray-400">{{ labels.eirNoDamage }}</p>
				<ul v-else class="space-y-1.5 text-sm">
					<li v-for="(d, i) in data.damages" :key="i" class="flex items-start gap-2 text-gray-800">
						<Icon name="alert-triangle" :size="14" class="mt-0.5 shrink-0 text-amber-500" />
						<span class="min-w-0">
							<span class="font-medium">{{ d.item_name || d.item }}</span>
							<span v-if="d.damage_type" class="text-gray-500"> · {{ labels.eirDamageCode }} {{ d.damage_type }}</span>
							<span v-if="d.repair_code" class="text-gray-500"> / {{ labels.eirRepairCode }} {{ d.repair_code }}</span>
							<span v-if="d.damage_description" class="block text-xs text-gray-400">{{ d.damage_description }}</span>
						</span>
					</li>
				</ul>
			</section>

			<div class="flex flex-wrap items-center gap-2">
				<a :href="printUrl(data)" target="_blank" rel="noopener" class="oak-btn oak-btn-secondary inline-flex px-3 py-2">
					<Icon name="printer" :size="16" /> {{ labels.cleaningPrint }}
				</a>
				<button
					v-if="data.docstatus === 1 && revisionFor !== data.name"
					type="button"
					class="oak-btn oak-btn-secondary inline-flex px-3 py-2"
					@click="openRevision(data.name)"
				>
					<Icon name="rotate-ccw" :size="16" /> {{ labels.eirReqRevision }}
				</button>
			</div>

			<!-- Revision request: reason (optional) + send; notifies Admin Ops server-side. -->
			<section v-if="revisionFor === data.name" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.eirReqRevision }}</p>
				<p class="text-xs text-gray-400">{{ labels.eirReqRevisionHint }}</p>
				<textarea v-model.trim="revisionReason" rows="2" :placeholder="labels.eirReqRevisionReason" class="oak-input"></textarea>
				<div class="flex items-center gap-2">
					<button type="button" class="oak-btn oak-btn-primary px-3 py-2" :disabled="revisionRes.loading" @click="sendRevision(data.name)">
						<Icon v-if="!revisionRes.loading" name="send" :size="16" />
						{{ revisionRes.loading ? "…" : labels.eirReqRevisionSend }}
					</button>
					<button type="button" class="oak-btn oak-btn-secondary px-3 py-2" :disabled="revisionRes.loading" @click="revisionFor = ''">
						{{ labels.confirmCancel }}
					</button>
				</div>
			</section>
		</template>
	</HistoryPage>
</template>

<script setup>
import { ref } from "vue"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")

// Revision request: which EIR's reason box is open, its text, and the POST resource.
const revisionFor = ref("")
const revisionReason = ref("")
function openRevision(name) {
	revisionFor.value = name
	revisionReason.value = ""
}
const revisionRes = createResource({
	url: "container_depot.ess.inspections.eir_request_revision",
	method: "POST",
	onSuccess() {
		toast.success(labels.eirReqRevisionSent)
		revisionFor.value = ""
		revisionReason.value = ""
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
function sendRevision(name) {
	revisionRes.submit({ inspection: name, reason: revisionReason.value || undefined })
}

function statusText(r) {
	if (r.docstatus === 1) return labels.eirStatusSubmitted
	if (r.docstatus === 2) return labels.eirStatusCancelled
	return labels.eirStatusDraft
}
function statusClass(r) {
	if (r.docstatus === 1) return "bg-leaf-100 text-leaf-800"
	if (r.docstatus === 2) return "bg-gray-200 text-gray-600"
	return "bg-amber-100 text-amber-800"
}
function cells(d) {
	return [
		{ label: labels.eirType, value: d.inspection_type },
		{ label: labels.eirTankStatus, value: d.tank_status },
		{ label: labels.eirDate, value: fmtDate(d.eir_date) },
		{ label: labels.depotLabel, value: d.depot },
		{ label: labels.eirVoucher, value: d.referred_voucher },
		{ label: labels.eirTruck, value: d.truck_no },
		{ label: labels.eirDriver, value: d.driver },
		{ label: labels.eirEmkl, value: d.emkl },
	]
}
function printUrl(d) {
	return `/api/method/frappe.utils.print_format.download_pdf?doctype=Inspection&name=${encodeURIComponent(
		d.name
	)}&format=EIR%20Format&no_letterhead=1`
}
</script>
