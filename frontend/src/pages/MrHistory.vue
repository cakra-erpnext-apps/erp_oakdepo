<template>
	<HistoryPage
		:title="labels.mrHistoryTitle"
		icon="tool"
		back-to="/mr"
		:back-label="labels.mrTitleFull"
		list-url="container_depot.ess.repairs.mr_history"
		detail-url="container_depot.ess.repairs.mr_order_detail"
		detail-param="repair_order"
		:search-placeholder="labels.mrHistorySearch"
		:count-label="labels.mrHistoryCount"
	>
		<template #row="{ item }">
			<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="tool" :size="16" /></span>
			<div class="min-w-0 flex-1">
				<div class="flex items-center justify-between gap-2">
					<p class="truncate font-semibold text-gray-900">{{ item.container_no || item.container }}</p>
					<span class="oak-chip shrink-0" :class="statusClass(item.status)">{{ statusText(item.status) }}</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between gap-2 text-xs text-gray-500">
					<span class="truncate">{{ item.repair_order_id }}</span>
					<span class="shrink-0">{{ fmtDate(item.completion_date || item.creation) }}</span>
				</div>
				<p v-if="item.principal" class="truncate text-[11px] text-gray-400">{{ item.principal }}</p>
			</div>
		</template>

		<!-- The whole record, not a summary. This screen is where a finished M&R is read back
		     — by the reviewer opening it out of "Diajukan Review", and by anyone asked later
		     what was done to a tank — so it carries what the Desk form carries: the tank, who
		     worked it and when, what the EIR found (with its photos), what was fitted, and the
		     proof photos. Per-line prices stay out: the depot PWA has never shown them (see
		     the module docstring in mr.py) and a Riwayat entry is not the place to start. -->
		<template #detail="{ data }">
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="font-mono text-xs text-gray-400">{{ data.repair_order_id }}</p>
						<h2 class="truncate text-lg font-extrabold text-gray-900">{{ data.container_no }}</h2>
					</div>
					<span class="oak-chip shrink-0" :class="statusClass(data.status)">{{ statusText(data.status) }}</span>
				</div>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="c in tankCells(data)" :key="c.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
				<p v-if="data.owner_note" class="rounded-lg bg-amber-50 p-2 text-xs text-amber-700">
					<Icon name="message-square" :size="12" /> {{ data.owner_note }}
				</p>
			</section>

			<!-- Who worked it and when, plus the papers it came from. -->
			<section class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.mrWorkRecord }}</p>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="c in workCells(data)" :key="c.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
			</section>

			<!-- What the EIR found — with its photos, the same strip the execution screen shows.
			     A damage list without pictures is the half of the record nobody can check. -->
			<section v-if="(data.damages || []).length" class="oak-card space-y-3 p-4">
				<p class="oak-section-title">{{ labels.mrDamagesTitle }}</p>
				<div v-for="(d, i) in data.damages" :key="i" class="rounded-xl border border-gray-100 p-3 space-y-2">
					<p class="font-semibold text-gray-900">{{ d.component || d.area || "—" }}</p>
					<div class="flex flex-wrap gap-1.5 text-xs">
						<span v-if="d.damage_code" class="oak-chip bg-red-50 text-red-700">
							{{ labels.mrCodeDamage }}: {{ d.damage_code }}<span v-if="d.damage_desc"> — {{ d.damage_desc }}</span>
						</span>
						<span v-if="d.repair_code" class="oak-chip bg-blue-50 text-blue-700">
							{{ labels.mrCodeRepair }}: {{ d.repair_code }}<span v-if="d.repair_desc"> — {{ d.repair_desc }}</span>
						</span>
					</div>
					<p v-if="d.damage_description" class="text-sm text-gray-600">{{ d.damage_description }}</p>
					<div v-if="(d.photos || []).length" class="flex flex-wrap gap-2">
						<button
							v-for="(ph, pi) in d.photos"
							:key="pi"
							type="button"
							class="oak-press"
							@click="openLightbox(d.photos, pi)"
						>
							<img :src="ph" class="h-16 w-16 rounded-lg border border-gray-200 object-cover" />
						</button>
					</div>
				</div>
			</section>

			<!-- What was actually done, and the proof — one card per line, the same shape the
			     execution screen uses, so a job reads the same after it closes as it did while
			     it was open. -->
			<section class="oak-card space-y-3 p-4">
				<div>
					<p class="oak-section-title">{{ labels.mrExecPartsTitle }}</p>
					<p class="mt-0.5 text-xs text-gray-400">{{ labels.mrWorkPhotosHint }}</p>
				</div>
				<p v-if="!(data.used_items || []).length" class="py-2 text-center text-sm text-gray-400">{{ labels.mrNoUsed }}</p>
				<div
					v-for="(u, i) in data.used_items"
					:key="i"
					class="rounded-xl border p-3 space-y-2"
					:class="u.decision === 'Rejected' ? 'border-red-100 bg-red-50/40' : 'border-gray-100'"
				>
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0">
							<p class="font-semibold text-gray-900">{{ u.item_name || u.item }}</p>
							<p class="text-xs text-gray-500">
								{{ labels.mrQty }} {{ u.quantity }}<span v-if="u.warehouse"> · {{ u.warehouse }}</span>
							</p>
							<p v-if="u.remark" class="text-xs text-gray-400">{{ u.remark }}</p>
							<p v-if="u.owner_remark" class="text-xs text-amber-700">{{ u.owner_remark }}</p>
						</div>
						<span class="oak-chip shrink-0" :class="decisionClass(u.decision)">{{ statusText(u.decision) }}</span>
					</div>
					<!-- A line the owner struck out was never repaired, so it has no proof to
					     show; the empty note below is for the ones that should have some. -->
					<div v-if="photosFor(data, u).length" class="grid grid-cols-3 gap-2">
						<button
							v-for="(ph, pi) in photosFor(data, u)"
							:key="pi"
							type="button"
							class="oak-press relative aspect-square"
							@click="openLightbox(photosFor(data, u).map((x) => x.photo), pi)"
						>
							<img :src="ph.photo" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
							<span
								v-if="ph.caption"
								class="absolute inset-x-0 bottom-0 truncate rounded-b-lg bg-black/60 px-1 py-0.5 text-[10px] text-white"
							>{{ ph.caption }}</span>
						</button>
					</div>
					<p v-else-if="u.decision !== 'Rejected'" class="text-xs text-gray-300">{{ labels.mrNoPhotos }}</p>
				</div>
			</section>

			<!-- Photos whose line is gone (the estimate was rewound and rebuilt after they were
			     taken). They are still evidence, so they are shown rather than silently lost. -->
			<section v-if="orphanPhotos(data).length" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.mrWorkPhotos }}</p>
				<div class="grid grid-cols-3 gap-2">
					<button
						v-for="(ph, i) in orphanPhotos(data)"
						:key="i"
						type="button"
						class="oak-press relative aspect-square"
						@click="openLightbox(orphanPhotos(data).map((x) => x.photo), i)"
					>
						<img :src="ph.photo" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
						<span
							v-if="ph.caption"
							class="absolute inset-x-0 bottom-0 truncate rounded-b-lg bg-black/60 px-1 py-0.5 text-[10px] text-white"
						>{{ ph.caption }}</span>
					</button>
				</div>
			</section>

			<section v-if="data.remarks" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.mrRemarks }}</p>
				<p class="whitespace-pre-line text-sm text-gray-800">{{ data.remarks }}</p>
			</section>

			<!-- A job that is still "Diajukan Review" is not history yet — it is the team's own
			     submission, and pulling it back is their own correction. The button lives on the
			     worklist row too, but a row is where you TRIAGE; this is where you actually read
			     what you sent, and finding no way to act on it from here means going back and
			     hunting for the row again.

			     This slot is also where "Ajukan Revisi" will go for a CLOSED order — same idea,
			     different question: pulling back your own submission needs nobody's permission,
			     re-opening a finished one needs Admin Ops. -->
			<template v-if="data.status === 'Pending Review'">
				<button
					type="button"
					class="oak-btn oak-btn-secondary w-full py-2.5"
					:disabled="withdrawRes.loading"
					@click="withdraw(data)"
				>
					<Icon name="rotate-ccw" :size="16" />
					{{ withdrawRes.loading ? "…" : labels.mrWithdrawReview }}
				</button>
				<p class="text-center text-xs text-gray-400">{{ labels.mrWithdrawReviewHint }}</p>
			</template>

			<!-- A CLOSED order cannot be pulled back by the team — it is Desk's record now — so
			     they ask instead. One standing request is enough: once raised, the reason is
			     shown in place of the button. Not offered once the order has reached an invoice;
			     undoing that is an accounting decision and the server refuses it anyway, and a
			     button that always throws is worse than no button. -->
			<template v-else-if="data.status === 'Completed'">
				<section v-if="data.reopen_requested" class="oak-card border-orange-200 bg-orange-50 space-y-1 p-4">
					<p class="font-semibold text-orange-800">
						<Icon name="rotate-ccw" :size="15" /> {{ labels.mrReopenRequested }}
					</p>
					<p v-if="data.reopen_note" class="whitespace-pre-line text-sm text-orange-900">{{ data.reopen_note }}</p>
				</section>
				<template v-else-if="(data.billing_status || 'Unbilled') === 'Unbilled'">
					<button
						v-if="revisionFor !== data.name"
						type="button"
						class="oak-btn oak-btn-secondary w-full py-2.5"
						@click="revisionFor = data.name"
					>
						<Icon name="rotate-ccw" :size="16" /> {{ labels.mrReqRevision }}
					</button>
					<section v-else class="oak-card space-y-2 p-4">
						<p class="oak-section-title">{{ labels.mrReqRevision }}</p>
						<p class="text-xs text-gray-400">{{ labels.mrReqRevisionHint }}</p>
						<textarea
							v-model.trim="revisionReason"
							rows="2"
							:placeholder="labels.mrReqRevisionReason"
							class="oak-input"
						></textarea>
						<div class="flex gap-2">
							<button
								type="button"
								class="oak-btn oak-btn-primary px-3 py-2"
								:disabled="revisionRes.loading"
								@click="sendRevision(data)"
							>
								<Icon v-if="!revisionRes.loading" name="send" :size="16" />
								{{ revisionRes.loading ? "…" : labels.mrReqRevisionSend }}
							</button>
							<button
								type="button"
								class="oak-btn oak-btn-secondary px-3 py-2"
								:disabled="revisionRes.loading"
								@click="revisionFor = ''"
							>
								{{ labels.mrBack }}
							</button>
						</div>
					</section>
				</template>
			</template>
		</template>
	</HistoryPage>
</template>

<script setup>
import { ref } from "vue"
import { useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels, repairStatusLabels } from "@/utils/labels"
import { openLightbox } from "@/utils/lightbox"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"

const router = useRouter()

// Pending Review -> In Progress. The order stops being a finished record the moment this
// lands, so staying on the Riwayat screen would leave the operator looking at a page that no
// longer describes it. Send them straight into the form they can now fix, rather than back to
// a list they would have to search.
const withdrawRes = createResource({
	url: "container_depot.ess.repairs.mr_withdraw_review",
	method: "POST",
	onError: (e) => toast.error(e?.messages?.[0] || e?.message || labels.error),
})
function withdraw(d) {
	withdrawRes.submit({ repair_order: d.name }, {
		onSuccess: () => {
			toast.success(labels.mrWithdrawReviewDone)
			router.push({ path: "/mr", query: { o: d.name } })
		},
	})
}

// "Ajukan Revisi" on a CLOSED order — a request, not an action: it notifies Admin Ops and
// flags the order, and nothing about the M&R moves until they decide. Same shape as the
// cleaning Riwayat's, which is the screen the operators already know this from.
const revisionFor = ref("")
const revisionReason = ref("")
const revisionRes = createResource({
	url: "container_depot.ess.repairs.mr_request_revision",
	method: "POST",
	onError: (e) => toast.error(e?.messages?.[0] || e?.message || labels.error),
})
function sendRevision(d) {
	// Read before the fields are cleared — the standing-request banner below is painted from
	// it, and clearing first would show an empty reason for a request that had one.
	const reason = revisionReason.value
	revisionRes.submit(
		{ repair_order: d.name, reason },
		{
			onSuccess: () => {
				toast.success(labels.mrReqRevisionSent)
				revisionFor.value = ""
				revisionReason.value = ""
				// Mirror the flag locally so the standing request replaces the button straight
				// away, instead of leaving a form that would happily raise a second one.
				d.reopen_requested = 1
				d.reopen_note = reason
			},
		}
	)
}

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")
// Work timestamps carry the time of day: "started 08:12, finished 15:40" is the fact someone
// is looking for, and a bare date cannot answer it.
const fmtDateTime = (v) => (v ? String(v).slice(0, 16).replace("T", " ") : "")

function statusText(s) {
	return repairStatusLabels[s] || s || "—"
}
function statusClass(s) {
	if (s === "Completed") return "bg-leaf-100 text-leaf-800"
	if (s === "Rejected") return "bg-red-100 text-red-700"
	if (s === "Cancelled") return "bg-gray-200 text-gray-600"
	return "bg-amber-100 text-amber-800"
}
function decisionClass(d) {
	if (d === "Approved") return "bg-leaf-100 text-leaf-800"
	if (d === "Rejected") return "bg-red-100 text-red-700"
	return "bg-gray-100 text-gray-500"
}

// The tank as it stood — the same spec block the execution form shows, so the record does not
// shrink the moment the job closes.
function tankCells(d) {
	return [
		{ label: labels.cleaningClient, value: d.client },
		{ label: labels.cleaningTankType, value: d.tank_type },
		{ label: labels.equipmentType, value: d.equipment_type },
		{ label: labels.cleaningCapacity, value: d.capacity },
		{ label: labels.cleaningPrevCargo, value: d.previous_cargo },
		{ label: labels.cleaningTare, value: d.tare },
		{ label: labels.cleaningMgw, value: d.mgw },
		{ label: labels.cleaningMfgDate, value: fmtDate(d.date_of_manufacture) },
		{ label: labels.cleaningLastTest, value: fmtDate(d.last_test_date) },
	]
}

// Who, when, and off which paperwork. Blank cells are dropped rather than printed as "—":
// an order approved without an owner round has no requested_on, and eight empty rows would
// bury the four that say something.
function workCells(d) {
	return [
		{ label: labels.mrTechnician, value: d.technician },
		{ label: labels.cleaningRefEir, value: d.inspection },
		{ label: labels.reffDoc, value: d.reff_doc },
		{ label: labels.mrStartDate, value: fmtDateTime(d.start_date) },
		{ label: labels.mrDoneDate, value: fmtDateTime(d.completion_date) },
		{ label: labels.mrRequestedOn, value: fmtDateTime(d.requested_on) },
		{ label: labels.mrDecidedOn, value: fmtDateTime(d.decided_on) },
		{ label: labels.mrRevisionNo, value: d.revision_no ? String(d.revision_no) : "" },
	].filter((c) => c.value)
}

// The photos proving one line. Matched on the ROW first (the same item can be on the order
// twice) and on the item as a fallback, which is what a photo attached from the Desk carries.
function photosFor(d, line) {
	return (d.work_photos || []).filter((p) =>
		p.used_item ? p.used_item === line.name : p.item === line.item
	)
}

// Evidence whose line no longer exists — a rewind to Draft rebuilds used_items, and a photo
// taken before that keeps pointing at a row id that is gone. Shown on its own rather than
// dropped: it is still a picture of this tank being worked on.
function orphanPhotos(d) {
	const lines = d.used_items || []
	return (d.work_photos || []).filter(
		(p) => !lines.some((u) => (p.used_item ? p.used_item === u.name : p.item === u.item))
	)
}
</script>
