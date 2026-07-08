<template>
	<HistoryPage
		:title="labels.surveyPosHistoryTitle"
		icon="map-pin"
		back-to="/survey-position"
		:back-label="labels.surveyPosTitle"
		list-url="container_depot.ess.position_survey.position_history"
		detail-url="container_depot.ess.position_survey.position_detail"
		detail-param="name"
		:search-placeholder="labels.surveyPosSearch"
		:count-label="labels.surveyPosHistoryCount"
	>
		<template #row="{ item }">
			<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-600"><Icon name="map-pin" :size="16" /></span>
			<div class="min-w-0 flex-1">
				<div class="flex items-center justify-between gap-2">
					<p class="truncate font-semibold text-gray-900">{{ item.container_no || item.container }}</p>
					<span class="oak-chip shrink-0" :class="statusClass(item.status)">{{ statusText(item.status) }}</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between gap-2 text-xs text-gray-500">
					<span class="truncate">{{ item.location_note || item.name }}</span>
					<span class="shrink-0">{{ fmtDate(item.approved_on || item.surveyed_on || item.creation) }}</span>
				</div>
			</div>
		</template>

		<template #detail="{ data }">
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="font-mono text-xs text-gray-400">{{ data.name }}</p>
						<h2 class="truncate text-lg font-extrabold text-gray-900">{{ data.container_no || data.container }}</h2>
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

			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.surveyPosSection }}</p>
				<p class="whitespace-pre-line text-sm text-gray-800">{{ data.location_note || "—" }}</p>
				<p v-if="data.survey_notes" class="text-xs text-gray-500">{{ data.survey_notes }}</p>
				<p v-if="data.approval_note" class="text-xs text-leaf-600">
					<Icon name="check-circle" :size="11" /> {{ data.approval_note }}
				</p>
			</section>

			<section v-if="(data.photos || []).length" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.surveyPosPhotos }}</p>
				<div class="grid grid-cols-3 gap-2">
					<a v-for="(url, i) in data.photos" :key="i" :href="url" target="_blank" rel="noopener" class="block">
						<img :src="url" class="aspect-square w-full rounded-lg object-cover" />
					</a>
				</div>
			</section>
		</template>
	</HistoryPage>
</template>

<script setup>
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")

function statusText(s) {
	if (s === "Confirmed") return labels.surveyPosStatusConfirmed
	if (s === "Surveyed") return labels.surveyPosStatusSurveyed
	if (s === "Pending Survey") return labels.surveyPosStatusPending
	if (s === "Cancelled") return labels.surveyPosStatusCancelled
	return s || "—"
}
function statusClass(s) {
	if (s === "Confirmed") return "bg-leaf-100 text-leaf-800"
	if (s === "Cancelled") return "bg-red-100 text-red-700"
	if (s === "Surveyed") return "bg-brand-100 text-brand-700"
	return "bg-gray-200 text-gray-600"
}
function cells(d) {
	return [
		{ label: labels.depot, value: d.depot },
		{ label: labels.surveyPosSurveyedBy, value: d.surveyed_by },
		{ label: labels.surveyPosApprovedBy, value: d.approved_by },
		{ label: "Booking", value: d.booking },
	]
}
</script>
