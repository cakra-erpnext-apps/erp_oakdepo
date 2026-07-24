<template>
	<HistoryPage
		:title="labels.cleaningHistoryTitle"
		icon="droplet"
		back-to="/cleaning"
		:back-label="labels.cleaningTitle"
		list-url="container_depot.ess.cleaning.cleaning_history"
		detail-url="container_depot.ess.cleaning.cleaning_order_detail"
		detail-param="cleaning_order"
		:search-placeholder="labels.cleaningOrdersSearch"
		:count-label="labels.cleaningHistoryCount"
	>
		<template #row="{ item }">
			<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-600"><Icon name="droplet" :size="16" /></span>
			<div class="min-w-0 flex-1">
				<div class="flex items-center justify-between gap-2">
					<p class="truncate font-semibold text-gray-900">{{ item.container_no || item.container }}</p>
					<span class="oak-chip shrink-0" :class="statusClass(item.status)">{{ statusText(item.status) }}</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between gap-2 text-xs text-gray-500">
					<span class="truncate">
						{{ item.order_id }}<span v-if="item.service_count"> · {{ item.service_count }} {{ labels.cleaningServicesCount }}</span>
					</span>
					<span class="shrink-0">{{ fmtDate(item.cleaning_end || item.order_created) }}</span>
				</div>
			</div>
		</template>

		<template #detail="{ data }">
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="font-mono text-xs text-gray-400">{{ data.order_id }}</p>
						<h2 class="truncate text-lg font-extrabold text-gray-900">{{ data.container_no }}</h2>
					</div>
					<span class="oak-chip shrink-0" :class="statusClass(data.status)">{{ statusText(data.status) }}</span>
				</div>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="c in cells(data)" :key="c.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
			</section>

			<section v-if="(data.cleaning_services || []).length" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningType }}</p>
				<ul class="space-y-1 text-sm">
					<li v-for="s in data.cleaning_services" :key="s.item_code" class="flex items-center gap-2 text-gray-800">
						<Icon name="check" :size="14" class="shrink-0 text-leaf-600" />
						<span class="truncate">{{ s.item_name || s.item_code }}</span>
					</li>
				</ul>
			</section>

			<div class="flex flex-wrap gap-2">
				<a :href="printOrderUrl(data)" target="_blank" rel="noopener" class="oak-btn oak-btn-secondary inline-flex px-3 py-2">
					<Icon name="printer" :size="16" /> {{ labels.cleaningPrint }}
				</a>
			</div>
		</template>
	</HistoryPage>
</template>

<script setup>
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")

function statusText(s) {
	if (s === "Completed") return labels.cleaningStatusCompleted
	if (s === "Cancelled") return labels.cleaningStatusCancelled
	return s || "—"
}
function statusClass(s) {
	if (s === "Completed") return "bg-leaf-100 text-leaf-800"
	if (s === "Cancelled") return "bg-red-100 text-red-700"
	return "bg-gray-200 text-gray-600"
}
function cells(d) {
	return [
		{ label: labels.cleaningClient, value: d.client },
		{ label: labels.cleaningPrevCargo, value: d.previous_cargo },
		{ label: labels.cleaningTankType, value: d.tank_type },
		{ label: labels.cleaningRefEir, value: d.inspection },
		{ label: labels.cleaningDateIssue, value: fmtDate(d.date_of_issue) },
	]
}
function printOrderUrl(d) {
	return `/api/method/frappe.utils.print_format.download_pdf?doctype=Cleaning%20Order&name=${encodeURIComponent(
		d.name
	)}&format=Cleaning%20Order%20Format&no_letterhead=1`
}
</script>
