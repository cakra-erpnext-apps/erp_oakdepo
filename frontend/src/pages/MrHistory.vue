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
					<p class="truncate font-bold text-gray-900">
						{{ item.container_no || item.container
						}}<span v-if="item.principal" class="font-normal text-gray-500"> · {{ item.principal }}</span>
					</p>
					<span class="oak-chip shrink-0" :class="chip(item.status).tone">{{ chip(item.status).label }}</span>
				</div>
				<div class="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-gray-500">
					<span class="truncate">{{ rowSubtitle(item) }}</span>
					<span class="shrink-0">{{ fmtDate(item.completion_date || item.creation) }}</span>
				</div>
			</div>
		</template>

		<!-- The whole record, not a summary. This screen is where a finished M&R is read back
		     — by the reviewer opening it out of "Diajukan Review", and by anyone asked later
		     what was done to a tank — so it carries what the Desk form carries: the tank, who
		     worked it and when, how it got approved, what the EIR found (with its photos),
		     what was fitted, and the proof photos. Per-line prices stay out: the depot PWA has
		     never shown them (see the module docstring in mr.py) and a Riwayat entry is not
		     the place to start. -->
		<template #detail="{ data }">
			<!-- Which tank, off which papers, and the three numbers the record is asked for:
			     how much work, how long it took, and who did it. -->
			<section class="oak-card space-y-3 p-4">
				<div class="flex items-start justify-between gap-3">
					<div class="min-w-0">
						<p class="truncate text-lg font-extrabold text-gray-900">{{ data.container_no }}</p>
						<p class="truncate text-xs text-gray-500">{{ subtitle(data) }}</p>
					</div>
					<div class="flex shrink-0 flex-col items-end gap-1">
						<span class="oak-chip" :class="chip(data.status).tone">{{ chip(data.status).label }}</span>
						<p class="font-mono text-[11px] text-gray-400">{{ data.repair_order_id }}</p>
					</div>
				</div>
				<dl class="grid grid-cols-3 gap-x-3 border-t border-gray-100 pt-3 text-sm">
					<div v-for="c in factCells(data)" :key="c.label" class="min-w-0">
						<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-semibold text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
			</section>

			<!-- How this order got here — see MrTimeline.vue. -->
			<MrTimeline :data="data" />

			<!-- What was actually done, and the proof — one card per line, the same shape the
			     work form uses, so a job reads the same after it closes as it did while it was
			     open. -->
			<section
				v-for="(u, i) in data.used_items || []"
				:key="i"
				class="oak-card space-y-3 p-4"
				:class="u.decision === 'Rejected' ? 'border-red-100 bg-red-50/40' : ''"
			>
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<p class="truncate font-bold text-gray-900">{{ u.item_name || u.item }}</p>
						<p class="text-xs text-gray-500">
							{{ labels.mrQty }} {{ u.quantity }}<span v-if="u.warehouse"> · {{ u.warehouse }}</span>
						</p>
						<p v-if="u.remark" class="text-xs text-gray-400">{{ u.remark }}</p>
						<p v-if="u.owner_remark" class="text-xs text-amber-700">{{ u.owner_remark }}</p>
					</div>
					<span class="oak-chip shrink-0" :class="decisionClass(u.decision)">{{ statusText(u.decision) }}</span>
				</div>
				<!-- A line the owner struck out was never repaired, so it has no proof to show;
				     the empty note below is for the ones that should have some. -->
				<div v-if="photosFor(data, u).length" class="grid grid-cols-2 items-start gap-2">
					<div v-for="(ph, pi) in photosFor(data, u)" :key="pi" class="space-y-1">
						<button
							type="button"
							class="oak-press block aspect-square w-full"
							@click="openLightbox(photosFor(data, u).map((x) => x.photo), pi)"
						>
							<img :src="ph.photo" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
						</button>
						<p v-if="ph.caption" class="text-[11px] text-gray-600">{{ ph.caption }}</p>
					</div>
				</div>
				<p v-else-if="u.decision !== 'Rejected'" class="text-xs text-gray-300">{{ labels.mrNoPhotos }}</p>
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

			<!-- What the EIR found, folded away: on a closed job it is the background to the
			     work above, not the thing being read. The count stays on the summary line so
			     nobody has to open it to learn there is nothing inside. -->
			<section v-if="(data.damages || []).length" class="oak-card space-y-3 p-4">
				<button
					type="button"
					class="flex w-full items-center justify-between gap-2 text-left"
					@click="damagesOpen = !damagesOpen"
				>
					<p class="oak-section-title">{{ labels.mrDamagesTitle }}</p>
					<span class="flex shrink-0 items-center gap-1 text-[11px] text-gray-400">
						{{ labels.mrFindingsCount.replace("{n}", data.damages.length) }}
						<Icon :name="damagesOpen ? 'chevron-up' : 'chevron-down'" :size="14" />
					</span>
				</button>
				<div v-if="damagesOpen" class="space-y-2">
					<MrDamageCard v-for="(d, i) in data.damages" :key="i" :damage="d" />
				</div>
			</section>

			<!-- Tank spec, and the papers it came off. Dropped entirely when the container
			     record carries none of it — a card holding one em dash is worse than no card. -->
			<section v-if="tankCells(data).length" class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.mrTankDetails }}</p>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-3 text-sm">
					<div v-for="c in tankCells(data)" :key="c.label" class="min-w-0">
						<dt class="text-[11px] uppercase tracking-wide text-gray-400">{{ c.label }}</dt>
						<dd class="truncate font-semibold text-gray-800">{{ c.value || "—" }}</dd>
					</div>
				</dl>
			</section>

			<section v-if="data.remarks" class="oak-card space-y-2 p-4">
				<p class="oak-section-title">{{ labels.mrRemarks }}</p>
				<p class="whitespace-pre-line text-sm text-gray-800">{{ data.remarks }}</p>
			</section>

			<!-- A job that is still "Diajukan Review" is not history yet — it is the team's own
			     submission, and pulling it back is their own correction. The button lives on the
			     worklist row too, but a row is where you TRIAGE; this is where you actually read
			     what you sent, and finding no way to act on it from here means going back and
			     hunting for the row again. -->
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
import { mrChip, workWindow } from "@/utils/mrStatus"
import { openLightbox } from "@/utils/lightbox"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import HistoryPage from "@/components/HistoryPage.vue"
import MrDamageCard from "@/components/MrDamageCard.vue"
import MrTimeline from "@/components/MrTimeline.vue"

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

// Folded by default — on a closed job the findings are background, and the count on the
// summary line already says whether opening them is worth it.
const damagesOpen = ref(false)

const fmtDate = (v) => (v ? String(v).slice(0, 10) : "—")

// "Mar 2019" — a tank's build date is read as a vintage, never as a day.
function fmtMonthYear(v) {
	if (!v) return ""
	const d = new Date(String(v).slice(0, 10) + "T00:00:00")
	return Number.isNaN(d.getTime())
		? String(v).slice(0, 7)
		: d.toLocaleDateString("id-ID", { month: "short", year: "numeric" })
}

function statusText(s) {
	return repairStatusLabels[s] || s || "—"
}
const chip = mrChip
function decisionClass(d) {
	if (d === "Approved") return "bg-leaf-100 text-leaf-800"
	if (d === "Rejected") return "bg-red-100 text-red-700"
	return "bg-gray-100 text-gray-500"
}

// The list row: how big the job was and how long it ran, falling back to the order id when
// neither was recorded.
function rowSubtitle(item) {
	const parts = [
		item.item_count ? labels.mrItemsN.replace("{n}", item.item_count) : "",
		workWindow(item.start_date, item.completion_date),
		item.technician || "",
	].filter(Boolean)
	return parts.length ? parts.join(" · ") : item.repair_order_id || ""
}

// Whose tank, what it is, what it last held, and which EIR it came off.
function subtitle(d) {
	return [
		d.client,
		d.tank_type,
		d.previous_cargo ? labels.mrExFmt.replace("{cargo}", d.previous_cargo) : "",
		d.inspection ? labels.mrFromEir.replace("{ref}", d.inspection) : "",
	]
		.filter(Boolean)
		.join(" · ")
}

// The three numbers a finished job is asked for. Not a table of every timestamp: the ones
// that describe the ORDER's life moved into the approval timeline, where their order is the
// point; these three describe the WORK.
function factCells(d) {
	return [
		{ label: labels.mrWorkCount, value: labels.mrItemsN.replace("{n}", (d.used_items || []).length) },
		{ label: labels.mrDuration, value: workWindow(d.start_date, d.completion_date) },
		{ label: labels.mrTechnician, value: d.started_by_name || d.technician },
	]
}

// The tank as it stood — the same spec block the work form shows, so the record does not
// shrink the moment the job closes.
function tankCells(d) {
	return [
		{ label: labels.cleaningCapacity, value: d.capacity },
		{ label: labels.mrTareMgw, value: [d.tare, d.mgw].filter(Boolean).join(" / ") },
		{ label: labels.equipmentType, value: d.equipment_type },
		{ label: labels.cleaningMfgDate, value: fmtMonthYear(d.date_of_manufacture) },
		{ label: labels.cleaningLastTest, value: d.last_test_date ? fmtDate(d.last_test_date) : "" },
		{ label: labels.reffDoc, value: d.reff_doc },
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
