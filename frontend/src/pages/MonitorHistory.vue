<template>
	<HistoryPage
		:title="labels.monitorHistoryTitle"
		icon="activity"
		back-to="/monitor"
		:back-label="labels.monitorTitle"
		list-url="container_depot.ess.inventory.activity_history"
		detail-url="container_depot.ess.inventory.activity_detail"
		detail-param="name"
		:search-placeholder="labels.monitorHistorySearch"
		:count-label="labels.monitorHistoryCount"
	>
		<template #row="{ item }">
			<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-600"><Icon :name="actIcon(item.activity_type)" :size="16" /></span>
			<div class="min-w-0 flex-1">
				<div class="flex items-center justify-between gap-2">
					<p class="truncate font-semibold text-gray-900">{{ item.container }}</p>
					<span class="oak-chip shrink-0 bg-gray-100 text-gray-600">{{ item.activity_type }}</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between gap-2 text-xs text-gray-500">
					<span class="truncate">{{ item.summary || statusMove(item) || "—" }}</span>
					<span class="shrink-0">{{ fmtDateTime(item.activity_time) }}</span>
				</div>
			</div>
		</template>

		<template #detail="{ data }">
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="text-xs text-gray-400">{{ fmtDateTime(data.activity_time) }}</p>
						<h2 class="truncate text-lg font-extrabold text-gray-900">{{ data.container }}</h2>
					</div>
					<span class="oak-chip shrink-0 bg-brand-50 text-brand-600">{{ data.activity_type }}</span>
				</div>

				<p v-if="data.summary" class="text-sm text-gray-800">{{ data.summary }}</p>

				<div v-if="data.from_status || data.to_status" class="rounded-xl border border-gray-100 p-3">
					<p class="mb-1 text-xs font-bold uppercase tracking-wide text-gray-400">{{ labels.storageStatusMove }}</p>
					<p class="text-sm font-medium text-gray-800">
						{{ data.from_status || "—" }}
						<Icon name="arrow-right" :size="14" class="mx-1 inline text-gray-400" />
						{{ data.to_status || "—" }}
					</p>
				</div>

				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="c in cells(data)" :key="c.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
			</section>
		</template>
	</HistoryPage>
</template>

<script setup>
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"

const fmtDateTime = (v) => (v ? String(v).slice(0, 16).replace("T", " ") : "—")

const ICONS = {
	Booking: "calendar",
	"Gate In": "log-in",
	"Inspection (EIR)": "clipboard",
	Cleaning: "droplet",
	Repair: "tool",
	"Periodic Test": "check-circle",
	"Order Bongkar": "download",
	"Order Muat": "upload",
	Release: "send",
	"Gate Out": "log-out",
	"Status Change": "refresh-cw",
}
function actIcon(t) {
	return ICONS[t] || "activity"
}
function statusMove(a) {
	if (a.from_status || a.to_status) return `${a.from_status || "—"} → ${a.to_status || "—"}`
	return ""
}
function cells(d) {
	return [
		{ label: labels.monitorRefDoc, value: d.reference_name },
		{ label: labels.monitorPerformedBy, value: d.performed_by },
		{ label: labels.cleaningClient, value: d.principal },
		{ label: labels.depotLabel, value: d.depot },
	]
}
</script>
