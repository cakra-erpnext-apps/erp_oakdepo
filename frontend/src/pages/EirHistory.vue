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
				<p class="oak-section-title">
					{{ labels.eirChecklistDamage }} ({{ data.damage_count || 0 }})
					<span v-if="data.finding_count" class="ml-1 text-xs font-normal text-amber-600">
						· {{ data.finding_count }} {{ labels.eirDamages.toLowerCase() }}
					</span>
				</p>
				<p v-if="!(data.damages || []).length" class="text-sm text-gray-400">{{ labels.eirNoDamage }}</p>
				<ul v-else class="space-y-3 text-sm">
					<!-- Kartu yang kembali "Acceptable" tetap dilist — itu bagian yang benar-benar
					     didatangi dan difoto — tapi ikonnya beda supaya temuan nyata tetap menonjol. -->
					<li v-for="(d, i) in data.damages" :key="i" class="flex items-start gap-2 text-gray-800">
						<Icon
							:name="d.is_finding ? 'alert-triangle' : 'check'"
							:size="14"
							class="mt-0.5 shrink-0"
							:class="d.is_finding ? 'text-amber-500' : 'text-leaf-500'"
						/>
						<div class="min-w-0 flex-1">
							<span class="font-medium">{{ d.item_name || d.item }}</span>
							<span v-if="d.damage_type" class="text-gray-500"> · {{ d.damage_label || d.damage_type }}</span>
							<span v-if="d.repair_code" class="text-gray-500"> / {{ d.repair_label || d.repair_code }}</span>
							<span v-if="d.damage_description" class="block text-xs text-gray-400">{{ d.damage_description }}</span>
							<!-- Bukti temuan ini, sejajar dengan yang ada di form Desk. -->
							<div v-if="(d.photos || []).length" class="mt-1.5 flex flex-wrap gap-1.5">
								<button
									v-for="(url, pi) in d.photos"
									:key="url"
									type="button"
									class="oak-press"
									@click="openLightbox(d.photos.map(photoSrc), pi)"
								>
									<img :src="photoSrc(url)" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
								</button>
							</div>
						</div>
					</li>
				</ul>
			</section>

			<!-- Album inspeksi: foto keliling tank dan foto bagian yang diperiksa tapi tidak
			     rusak — sama seperti tabel Foto per Item di Desk. -->
			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.eirPhotosTitle }} ({{ data.photo_count || 0 }})</p>
				<p v-if="!(data.photos || []).length" class="text-sm text-gray-400">{{ labels.eirNoPhotos }}</p>
				<div v-else class="flex flex-wrap gap-2">
					<button
						v-for="(p, i) in data.photos"
						:key="p.photo"
						type="button"
						class="oak-press w-[104px] text-left"
						@click="openLightbox((data.photos || []).map((x) => photoSrc(x.photo)), i)"
					>
						<img :src="photoSrc(p.photo)" class="h-24 w-[104px] rounded-lg border border-gray-200 object-cover" />
						<span class="mt-0.5 block truncate text-[11px]" :class="p.item_name ? 'text-gray-500' : 'text-gray-400'">
							{{ p.item_name || labels.eirPhotoUnsorted }}
						</span>
					</button>
				</div>
			</section>

			<div class="flex flex-wrap items-center gap-2">
				<button
					v-if="data.docstatus === 1 && revisionFor !== data.name"
					type="button"
					class="oak-btn oak-btn-secondary inline-flex px-3 py-2"
					@click="openRevision(data.name)"
				>
					<Icon name="rotate-ccw" :size="16" /> {{ labels.eirReqRevision }}
				</button>
				<!-- Awaiting review → the operator can pull it back to Draft and fix it (no
				     Admin Ops needed). Jumps straight into the editable form on success. -->
				<button
					v-if="data.docstatus === 0 && data.status === 'Pending Review'"
					type="button"
					class="oak-btn oak-btn-primary inline-flex px-3 py-2"
					:disabled="withdrawRes.loading"
					@click="withdrawReview(data)"
				>
					<Icon name="edit-3" :size="16" /> {{ withdrawRes.loading ? "…" : labels.eirWithdrawReview }}
				</button>
			</div>
			<p v-if="data.docstatus === 0 && data.status === 'Pending Review'" class="px-1 text-xs text-gray-400">
				{{ labels.eirWithdrawReviewHint }}
			</p>

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
import { useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { photoSrc } from "@/data/send"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"

const router = useRouter()
const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")

// Withdraw a "Pending Review" EIR back to an editable Draft, then open the form so the
// operator can fix it and re-send for review.
const withdrawRes = createResource({
	url: "container_depot.ess.inspections.eir_withdraw_review",
	method: "POST",
	onSuccess(data) {
		toast.success(labels.eirWithdrawReviewDone)
		const t = data?.inspection_type === "EIR-Out" ? "out" : "in"
		router.push({ path: "/eir", query: { e: data?.inspection, t } })
	},
	onError(err) {
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})
function withdrawReview(data) {
	withdrawRes.submit({ inspection: data.name })
}

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

// Single status vocabulary, identical to the Desk list (inspection_list.js) so the two
// surfaces never read differently: Batal / Revisi Diminta / Selesai / Menunggu Review / Draf.
function statusText(r) {
	if (r.docstatus === 2) return labels.eirStatusCancelled
	if (r.docstatus === 1 && r.revision_requested) return labels.eirStatusRevision
	if (r.docstatus === 1) return labels.eirStatusSubmitted
	if (r.status === "Pending Review") return labels.eirStatusPendingReview
	return labels.eirStatusDraft
}
function statusClass(r) {
	if (r.docstatus === 2) return "bg-gray-200 text-gray-600"
	if (r.docstatus === 1 && r.revision_requested) return "bg-orange-100 text-orange-800"
	if (r.docstatus === 1) return "bg-leaf-100 text-leaf-800"
	if (r.status === "Pending Review") return "bg-sky-100 text-sky-800"
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
		{ label: labels.eirEmkl, value: d.shipper },
	]
}
</script>
