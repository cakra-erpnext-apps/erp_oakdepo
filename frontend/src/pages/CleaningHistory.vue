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
					<span class="shrink-0 flex items-center gap-1.5">
						<span v-if="item.revision_requested" class="oak-chip bg-orange-100 text-orange-800">{{ labels.cleaningStatusRevision }}</span>
						{{ fmtDate(item.cleaning_end || item.order_created) }}
					</span>
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

			<section v-if="data.cleaning_instructions" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningInstructions }}</p>
				<p class="whitespace-pre-line text-sm text-gray-800">{{ data.cleaning_instructions }}</p>
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

			<!-- Who worked it and when — the same facts the Desk form keeps, so the Riwayat
			     entry stands on its own as the record of the job. -->
			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningTankDetails }}</p>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="c in workCells(data)" :key="c.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
			</section>

			<!-- Foto QC — the evidence the wash actually happened. Tap opens the full picture. -->
			<section v-if="(data.qc_photos || []).length" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningQcPhotos }}</p>
				<div class="grid grid-cols-3 gap-2">
					<button
						v-for="(p, i) in data.qc_photos"
						:key="i"
						type="button"
						class="oak-press relative aspect-square"
						@click="openLightbox(data.qc_photos.map((q) => photoSrc(q.photo)), i)"
					>
						<img :src="photoSrc(p.photo)" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
						<span
							v-if="p.caption"
							class="absolute inset-x-0 bottom-0 truncate rounded-b-lg bg-black/60 px-1 py-0.5 text-[10px] text-white"
						>{{ p.caption }}</span>
					</button>
				</div>
			</section>

			<section v-if="data.remarks" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningRemarks }}</p>
				<p class="whitespace-pre-line text-sm text-gray-800">{{ data.remarks }}</p>
			</section>

			<section v-if="data.signature" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningSignature }}</p>
				<img :src="photoSrc(data.signature)" class="h-24 rounded-lg border border-gray-200 bg-white object-contain p-1" />
				<p v-if="data.signed_by" class="text-xs text-gray-500">{{ data.signed_by }}</p>
			</section>

			<!-- A submitted order can't be edited from the PWA, so the operator asks Admin Ops
			     to reopen it instead — same door the EIR Riwayat gives (eir_request_revision).
			     One standing request is enough: once raised, the reason is shown instead of the
			     button. -->
			<section v-if="data.revision_requested" class="oak-card border-orange-200 bg-orange-50 space-y-1 p-4">
				<p class="font-semibold text-orange-800">
					<Icon name="rotate-ccw" :size="15" /> {{ labels.cleaningStatusRevision }}
				</p>
				<p v-if="data.revision_note" class="whitespace-pre-line text-sm text-orange-900">{{ data.revision_note }}</p>
			</section>
			<button
				v-else-if="data.docstatus === 1 && revisionFor !== data.name"
				type="button"
				class="oak-btn oak-btn-secondary w-full py-2.5"
				@click="openRevision(data.name)"
			>
				<Icon name="rotate-ccw" :size="16" /> {{ labels.cleaningReqRevision }}
			</button>
			<section v-else-if="revisionFor === data.name" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.cleaningReqRevision }}</p>
				<p class="text-xs text-gray-400">{{ labels.cleaningReqRevisionHint }}</p>
				<textarea v-model.trim="revisionReason" rows="2" :placeholder="labels.cleaningReqRevisionReason" class="oak-input"></textarea>
				<div class="flex gap-2">
					<button type="button" class="oak-btn oak-btn-primary px-3 py-2" :disabled="revisionRes.loading" @click="sendRevision(data.name)">
						<Icon v-if="!revisionRes.loading" name="send" :size="16" />
						{{ revisionRes.loading ? "…" : labels.cleaningReqRevisionSend }}
					</button>
					<button type="button" class="oak-btn oak-btn-secondary px-3 py-2" :disabled="revisionRes.loading" @click="revisionFor = ''">
						{{ labels.cleaningBack }}
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
import { photoSrc } from "@/data/send"
import { openLightbox } from "@/utils/lightbox"

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")
// Timestamps lose their seconds — the minute is what a reader of the record needs.
const fmtDateTime = (v) => (v ? String(v).slice(0, 16).replace("T", " ") : "")

// Revision request: which order's reason box is open, its text, and the POST resource.
// The request only notifies Admin Ops + flags the order — reopening stays their decision.
const revisionFor = ref("")
const revisionReason = ref("")
function openRevision(name) {
	revisionFor.value = name
	revisionReason.value = ""
}
const revisionRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_request_revision",
	method: "POST",
	onSuccess: () => {
		toast.success(labels.cleaningReqRevisionSent)
		revisionFor.value = ""
		revisionReason.value = ""
	},
	onError: (e) => toast.error(e?.messages?.[0] || e?.message || labels.error),
})
function sendRevision(name) {
	revisionRes.submit({ cleaning_order: name, reason: revisionReason.value || undefined })
}

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
// The job itself: who, where, when. Kept apart from the tank spec above so the two read as
// two different things.
function workCells(d) {
	return [
		{ label: labels.depotLabel, value: d.depot },
		{ label: labels.reffDoc, value: d.reff_doc },
		{ label: labels.cleaningWorkedBy, value: d.assigned_to },
		{ label: labels.cleaningStartAt, value: fmtDateTime(d.cleaning_start) },
		{ label: labels.cleaningEndAt, value: fmtDateTime(d.cleaning_end) },
		{ label: labels.cleaningSignedBy, value: d.signed_by },
		{ label: labels.cleaningPlaceIssue, value: d.place_of_issue },
	]
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
</script>
