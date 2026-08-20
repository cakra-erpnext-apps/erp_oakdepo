<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.mrTitleFull }}
				</h1>
				<p v-if="order" class="truncate font-mono text-[11px] text-gray-500">
					{{ order.repair_order_id }} · {{ order.container_no }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.mrExecOrdersHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link v-if="!order" to="/mr/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button v-if="order" class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
					<Icon name="arrow-left" :size="16" /> {{ labels.mrBack }}
				</button>
			</div>
		</div>

		<!-- OPENING AN ORDER — placeholder while its detail is fetched. Without this the
		     worklist just sat there unchanged after a tap, which reads as a dead button. -->
		<SkeletonDetail v-if="detailPending" :cells="6" :sections="3" />

		<!-- The detail could not be fetched and there is no cached copy to fall back on. -->
		<section v-else-if="detailFailed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ detailError }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="backToList">{{ labels.mrBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="retryDetail">{{ labels.retry }}</button>
			</div>
		</section>

		<!-- WORKLIST — same shape as the Cleaning worklist (/depot/cleaning): search, then
		     Semua / Belum / Dikerjakan toggles with counts, then a capped scroller of
		     fixed-height rows. M&R is triaged exactly the way cleaning is, so it reads the
		     same way; each row leads with the tank and WHOSE it is, because that is what the
		     operator sorts the queue by. -->
		<section v-else-if="!order" class="oak-section space-y-3">
			<div class="flex items-center gap-2">
				<Icon name="tool" :size="16" class="text-brand-500" />
				<p class="oak-section-title">{{ labels.mrOrdersList }}</p>
			</div>
			<div class="flex gap-2">
				<input
					v-model="search"
					class="oak-input uppercase"
					:placeholder="labels.mrOrdersSearch"
					autocapitalize="characters"
					autocorrect="off"
					autocomplete="off"
					spellcheck="false"
					enterkeyhint="search"
					@input="onSearchInput"
					@keyup.enter="reloadOrders"
				/>
				<button class="oak-btn oak-btn-secondary shrink-0 px-3" @click="reloadOrders">
					<Icon name="search" :size="16" />
				</button>
			</div>

			<!-- Belum / Dikerjakan split: an order Admin Ops handed over is "belum" until
			     Mulai moves it to In Progress; one sent for review leaves the worklist for
			     the section below it. -->
			<div class="grid grid-cols-3 gap-2">
				<button
					v-for="f in FILTERS"
					:key="f.key"
					class="oak-toggle flex items-center justify-center gap-1.5"
					:class="filter === f.key ? 'oak-toggle-on' : 'oak-toggle-off'"
					@click="filter = f.key"
				>
					{{ f.label }}
					<span class="oak-chip" :class="filter === f.key ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-500'">{{ f.count }}</span>
				</button>
			</div>

			<SkeletonList v-if="ordersRes.loading && !orders.length" />
			<p v-else-if="!visibleOrders.length" class="py-4 text-center text-sm text-gray-400">{{ emptyText }}</p>
			<!-- The scroller reveals about 5 rows (fixed 60px each); the rest scroll, so a
			     long queue never runs far down the page. -->
			<div v-else class="max-h-[300px] overflow-y-auto overscroll-contain">
				<ul class="divide-y divide-gray-100">
					<li v-for="o in visibleOrders" :key="o.name">
						<div class="flex h-[60px] items-center gap-3">
							<button class="oak-press flex h-full min-w-0 flex-1 items-center gap-3 text-left" @click="openOrder(o)">
								<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-50 text-brand-600">
									<Icon name="tool" :size="16" />
								</span>
								<div class="min-w-0 flex-1">
									<p class="truncate font-semibold text-gray-900">
										{{ o.container_no || o.container }}<span v-if="o.principal" class="font-normal text-gray-500"> · {{ o.principal }}</span>
									</p>
									<!-- One subtitle line: what state it is in, when it has to be out, and
									     how big the job is. Ordered by urgency so the truncation eats the
									     least important half first. -->
									<p class="flex items-center gap-1.5 text-[11px]">
										<span v-if="o.status === 'In Progress'" class="oak-chip shrink-0 bg-amber-100 text-amber-800">
											<Icon name="clock" :size="11" /> {{ labels.mrInProgress }}
										</span>
										<span v-if="o.target_lift_on" class="shrink-0 font-semibold" :class="liftClass(o.target_lift_on)">
											Lift-on {{ hMinus(o.target_lift_on) }}
										</span>
										<span class="truncate text-gray-400">
											<template v-if="o.item_count">{{ o.item_count }} {{ labels.mrItemsCount }}</template>
											<template v-else>{{ o.repair_order_id }}</template>
										</span>
									</p>
								</div>
							</button>
							<button
								v-if="o.status !== 'In Progress'"
								class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs"
								@click.stop="startOrder(o)"
							>
								{{ labels.mrStart }}
							</button>
						</div>
					</li>
				</ul>
			</div>
			<p v-if="visibleOrders.length" class="text-center text-xs text-gray-400">
				{{ visibleOrders.length }} {{ labels.mrOrdersCount }}
			</p>
		</section>

		<!-- Sent for review (Pending Review) — the field is done, Desk still has to check the
		     work and close it. Kept out of the worklist above: work waiting on somebody ELSE
		     must not sit among work waiting on YOU. -->
		<section v-if="!order && !detailPending && !detailFailed && (reviewRes.loading || reviewItems.length)" class="oak-section space-y-3">
			<div class="flex items-center gap-2">
				<Icon name="clock" :size="16" class="text-sky-500" />
				<p class="oak-section-title">{{ labels.mrReviewList }}</p>
				<span v-if="reviewItems.length" class="oak-chip bg-sky-100 text-sky-700">{{ reviewItems.length }}</span>
			</div>
			<ul v-if="reviewRes.loading && !reviewItems.length" class="space-y-2">
				<li v-for="n in 2" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
			</ul>
			<p v-else-if="!reviewItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.mrReviewEmpty }}</p>
			<ul v-else class="divide-y divide-gray-100">
				<li v-for="r in reviewItems" :key="r.name">
					<div class="flex items-center gap-3 py-2.5">
						<button type="button" class="oak-press flex min-w-0 flex-1 items-center gap-3 text-left" @click="goFinished(r)">
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-sky-50 text-sky-600"><Icon name="clock" :size="16" /></span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-semibold text-gray-900">
									{{ r.container_no || r.container }}<span v-if="r.principal" class="font-normal text-gray-500"> · {{ r.principal }}</span>
								</p>
								<p class="truncate text-[11px] text-gray-400">{{ r.repair_order_id || r.name }}</p>
							</div>
							<span class="oak-chip shrink-0 bg-sky-100 text-sky-800">{{ labels.mrStatusPendingReview }}</span>
						</button>
						<!-- Pulling it back is the team's own fix — no Admin Ops needed, and nothing
						     has left the warehouse since approval — so it sits on the row rather
						     than behind the detail. -->
						<button
							type="button"
							class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs"
							:disabled="withdrawRes.loading"
							@click.stop="withdrawReview(r)"
						>
							{{ labels.mrWithdrawReview }}
						</button>
					</div>
				</li>
			</ul>
		</section>

		<!-- Finished (Completed / Rejected / Cancelled) — the last few, full log behind Riwayat. -->
		<section v-if="!order && !detailPending && !detailFailed" class="oak-section space-y-3">
			<div class="flex items-center justify-between gap-2">
				<div class="flex items-center gap-2">
					<Icon name="check-circle" :size="16" class="text-leaf-600" />
					<p class="oak-section-title">{{ labels.mrCompleteList }}</p>
				</div>
				<router-link to="/mr/history" class="oak-link text-sm">{{ labels.mrListMore }}</router-link>
			</div>
			<ul v-if="doneRes.loading && !doneItems.length" class="space-y-2">
				<li v-for="n in 3" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
			</ul>
			<p v-else-if="!doneItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.mrCompleteEmpty }}</p>
			<ul v-else class="divide-y divide-gray-100">
				<li v-for="r in doneItems" :key="r.name">
					<button type="button" class="oak-press flex w-full items-center gap-3 py-2.5 text-left" @click="goFinished(r)">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="tool" :size="16" /></span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">
								{{ r.container_no || r.container }}<span v-if="r.principal" class="font-normal text-gray-500"> · {{ r.principal }}</span>
							</p>
							<p class="truncate text-xs text-gray-500">
								{{ r.repair_order_id }}<span v-if="r.completion_date"> · {{ fmtDate(r.completion_date) }}</span>
							</p>
						</div>
						<span class="oak-chip shrink-0" :class="doneChipClass(r.status)">{{ repairStatusLabel(r.status) }}</span>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</button>
				</li>
			</ul>
		</section>

		<!-- DETAIL (execution, read-only estimate) -->
		<template v-if="order">
			<!-- GATE: a handed-over (Pending) order must be started before its work detail is
			     shown — mirrors the Cleaning start gate. -->
			<section v-if="isPending" class="oak-card space-y-4 p-5 text-center">
				<span class="oak-icon-tile mx-auto h-14 w-14 bg-brand-50 text-brand-600"><Icon name="tool" :size="26" /></span>
				<div class="space-y-1">
					<p class="font-bold text-gray-900">{{ order.container_no || order.container }}</p>
					<p class="font-mono text-xs text-gray-400">{{ order.repair_order_id }}</p>
					<p class="text-sm text-gray-500">{{ labels.mrExecStartGate }}</p>
				</div>
				<button class="oak-btn oak-btn-primary w-full py-3 text-base" @click="startCurrent">
					{{ labels.mrStartFull }}
				</button>
			</section>

			<!-- Non-execution order opened via deep-link — managed in ERP. -->
			<section v-else-if="!isInProgress" class="oak-card border-amber-200 bg-amber-50 p-3">
				<p class="text-sm font-semibold text-amber-800">{{ labels.mrExecErpBanner }}</p>
			</section>

			<!-- WORK DETAIL — only once the order is In Progress (started). -->
			<template v-else>
				<section class="oak-card border-indigo-200 bg-indigo-50 p-3">
					<p class="text-sm font-semibold text-indigo-700">{{ labels.mrExecInProgress }}</p>
				</section>

				<!-- Tank header -->
				<section class="oak-card p-4">
					<p class="oak-section-title mb-2">{{ labels.mrTankDetails }}</p>
					<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
						<div v-for="cell in headerCells" :key="cell.label" class="min-w-0">
							<dt class="text-xs text-gray-400">{{ cell.label }}</dt>
							<dd class="truncate font-medium text-gray-800">{{ cell.value || "—" }}</dd>
						</div>
					</dl>
					<p v-if="order.inspection" class="mt-2 font-mono text-[11px] text-gray-400">
						{{ labels.mrRefEir }}: {{ order.inspection }}
					</p>
				</section>

				<!-- Damage findings (read-only, copied from EIR) -->
				<section class="oak-card p-4 space-y-3">
					<p class="oak-section-title">{{ labels.mrDamagesTitle }}</p>
					<p v-if="!order.damages || !order.damages.length" class="py-2 text-center text-sm text-gray-400">
						{{ labels.mrNoDamages }}
					</p>
					<div v-for="(d, i) in order.damages" :key="i" class="rounded-xl border border-gray-100 p-3 space-y-2">
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
						<div v-if="d.photos && d.photos.length" class="flex flex-wrap gap-2">
							<button v-for="(ph, pi) in d.photos" :key="pi" type="button" class="oak-press" @click="openLightbox(d.photos, pi)">
								<img :src="ph" class="h-20 w-20 rounded-lg border border-gray-200 object-cover" />
							</button>
						</div>
					</div>
				</section>

				<!-- Pekerjaan + bukti, ONE card per line: nama, qty, lalu fotonya.
				     They are two tables on the server (and two grids on the Desk) because their
				     lifetimes differ — the estimate freezes, the evidence is gathered mid-repair. On a
				     phone that split bought nothing and cost a lot: the same three item names were
				     printed twice, one screen apart, so the operator had to scroll past the whole
				     estimate to reach the camera for the line they were standing in front of.
				     Storage stays split; the screen does not. -->
				<section class="oak-card p-4 space-y-3">
					<div>
						<p class="oak-section-title">{{ labels.mrExecPartsTitle }}</p>
						<p class="mt-0.5 text-xs text-gray-400">{{ labels.mrWorkPhotosHint }}</p>
					</div>
					<p v-if="!photoGroups.length" class="py-2 text-center text-sm text-gray-400">{{ labels.mrNoUsed }}</p>
					<div v-for="g in photoGroups" :key="g.key" class="rounded-xl border border-gray-100 p-3 space-y-2">
						<div>
							<p class="font-semibold text-gray-900">{{ g.label }}</p>
							<p class="text-xs text-gray-500">
								{{ labels.mrQty }} {{ g.line.quantity }}<span v-if="g.line.on_hand != null"> · {{ labels.mrOnHand }} {{ g.line.on_hand }}</span>
								<!-- Each part names the gudang it was issued from when the owner approved. -->
								<span v-if="g.line.warehouse"> · {{ g.line.warehouse }}</span>
							</p>
							<p v-if="g.line.remark" class="text-xs text-gray-400">{{ g.line.remark }}</p>
						</div>
						<!-- One photo per ROW, not a wrapped strip of tiles: the caption has to be
						     typeable on a phone, and a text box the width of a 64px thumbnail is not.
						     Thumbnail left, keterangan filling the rest, delete on the right. -->
						<div v-if="g.photos.length" class="space-y-2">
							<div v-for="(ph, pi) in g.photos" :key="ph.photo" class="flex items-center gap-2">
								<button type="button" class="oak-press shrink-0" @click="openLightbox(g.photos.map((x) => photoSrc(x.photo)), pi)">
									<img :src="photoSrc(ph.photo)" class="h-14 w-14 rounded-lg border border-gray-200 object-cover" />
								</button>
								<input
									v-model="ph.caption"
									type="text"
									class="oak-input min-w-0 flex-1 px-2.5 py-2 text-sm"
									:placeholder="labels.mrPhotoCaption"
									@input="scheduleSave"
								/>
								<button
									type="button"
									class="oak-press shrink-0 p-2 text-gray-400"
									:aria-label="labels.mrRemove"
									@click="removePhoto(ph)"
								>
									<Icon name="trash-2" :size="16" />
								</button>
							</div>
						</div>
						<label class="flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-brand-300 bg-brand-50 py-2.5 text-sm font-medium text-brand-600 active:bg-brand-100">
							<input
								type="file"
								accept="image/*"
								capture="environment"
								multiple
								class="hidden"
								:disabled="g.uploading"
								@change="onPickPhotos(g, $event)"
							/>
							<Icon v-if="g.uploading" name="loader" :size="16" class="animate-spin" />
							<template v-else><Icon name="camera" :size="16" /> {{ labels.mrAddPhoto }}</template>
						</label>
					</div>
					<p v-if="photoErr" class="text-xs text-red-600">{{ photoErr }}</p>
					<p class="flex items-center gap-1.5 text-xs">
						<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
						<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600">
							<Icon name="check" :size="13" /> {{ labels.draftSaved }}
						</span>
						<span v-else class="text-gray-400">{{ labels.autosaveHint }}</span>
					</p>
				</section>

				<!-- Remarks (read-only) -->
				<section v-if="order.remarks" class="oak-card p-4">
					<p class="oak-section-title mb-1">{{ labels.mrRemarks }}</p>
					<p class="whitespace-pre-line text-sm text-gray-700">{{ order.remarks }}</p>
				</section>

				<!-- Hand the finished job to Desk. This does NOT close the order. -->
				<button class="oak-btn oak-btn-primary w-full py-3" :disabled="submitting" @click="confirmSubmit">
					<Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
					<span v-else>{{ labels.mrSubmitReview }}</span>
				</button>
				<p class="text-center text-xs text-gray-400">{{ labels.mrSubmitReviewHint }}</p>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue"
import { createResource } from "frappe-ui"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"
import { useRoute, useRouter } from "vue-router"
import { labels, repairStatusLabel } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { confirm } from "@/utils/confirm"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"

const route = useRoute()
const router = useRouter()

const fmtDate = (v) =>
	v
		? new Date(String(v).slice(0, 10) + "T00:00:00").toLocaleDateString("id-ID", {
				day: "numeric",
				month: "short",
				year: "numeric",
		  })
		: "—"

// Gate Out Plan target lift-on → countdown badge (H-minus) with urgency colour.
const liftDays = (v) => {
	if (!v) return null
	const target = new Date(String(v).slice(0, 10) + "T00:00:00")
	const today = new Date(new Date().toDateString())
	return Math.round((target - today) / 86400000)
}
const hMinus = (v) => {
	const d = liftDays(v)
	if (d === null) return ""
	if (d < 0) return `Lewat ${-d} hr`
	if (d === 0) return "Hari-H"
	return `H-${d}`
}
const liftClass = (v) => {
	const d = liftDays(v)
	if (d === null) return ""
	if (d <= 1) return "text-red-600"
	if (d <= 3) return "text-amber-600"
	return "text-brand-600"
}

const search = ref("")
const allOrders = ref([]) // what the server (or the offline cache) last said
const order = ref(null)
const used = ref([])

// Evidence photos — the whole album for this order, flat. Grouping happens in the view.
const workPhotos = ref([])
const photoErr = ref("")
const savedOk = ref(false) // last auto-save succeeded
const suppressSave = ref(false) // mute auto-save while a detail is being loaded

// --- status-driven view flags (execution phase only) -----------------------
//
// "Pending" is an order Admin Ops handed over that nobody has picked up yet; the team's
// first press is Mulai. An Approved order never reaches this screen — it has not been
// forwarded — so opening one by deep link falls through to the ERP banner.
const isPending = computed(() => order.value?.status === "Pending")
const isInProgress = computed(() => order.value?.status === "In Progress")
// Only approved lines are relevant to the field crew (rejected ones aren't repaired, and
// their parts were never issued).
const repairLines = computed(() => used.value.filter((u) => u.decision !== "Rejected"))

// Which group is mid-upload — one at a time is enough, and it keeps the flag off the photo
// rows themselves (which are sent to the server verbatim).
const uploading = ref(null)

// One group per line that was actually approved. A photo belongs to the group whose ROW it
// names; the fallback on `item` catches rows attached from the Desk, where a human picks the
// service/part and never sees a row id.
const photoGroups = computed(() =>
	repairLines.value.map((u) => ({
		key: u.name || u.item,
		line: u,
		label: u.item_name || u.item,
		uploading: uploading.value === (u.name || u.item),
		photos: workPhotos.value.filter((p) =>
			p.used_item ? p.used_item === u.name : p.item === u.item
		),
	}))
)

function doneChipClass(s) {
	if (s === "Completed") return "bg-leaf-100 text-leaf-800"
	if (s === "Rejected") return "bg-red-100 text-red-700"
	return "bg-gray-200 text-gray-600"
}

const ordersRes = cachedResource({
	url: "container_depot.ess.repairs.mr_execution",
	method: "GET",
	auto: true,
	onSuccess: (data) => (allOrders.value = data.items || []),
})

// How many finished orders the landing shows before "Lihat semua" takes over.
const LANDING_LIMIT = 5

// "Diajukan Review" — jobs finished in the field, waiting for Desk to check the work and
// close them. Opened read-only like a finished one; withdrawable from the row.
const reviewItems = ref([])
const reviewRes = cachedResource({
	url: "container_depot.ess.repairs.mr_pending_review",
	method: "GET",
	auto: true,
	onSuccess: (data) => (reviewItems.value = data.items || []),
})

const doneItems = ref([])
const doneRes = cachedResource({
	url: "container_depot.ess.repairs.mr_history",
	method: "GET",
	makeParams: () => ({ page_length: LANDING_LIMIT }),
	auto: true,
	onSuccess: (data) => (doneItems.value = data.items || []),
})

// Finished (or field-done) work has no editable form to open — the Riwayat detail takes an
// ?open= deep link and fetches the order straight from the server.
function goFinished(r) {
	router.push({ path: "/mr/history", query: { open: r.name } })
}

const withdrawRes = createResource({
	url: "container_depot.ess.repairs.mr_withdraw_review",
	method: "POST",
	onSuccess: () => {
		toast.success(labels.mrWithdrawReviewDone)
		reloadOrders()
		reviewRes.reload()
	},
	onError: (e) => toast.error(e?.messages?.[0] || e?.message || labels.error),
})
function withdrawReview(r) {
	withdrawRes.submit({ repair_order: r.name })
}

const orders = computed(() => allOrders.value)

function reloadOrders() {
	const s = search.value.trim()
	ordersRes.fetch(s ? { search: s } : {})
}

// Typing searches on its own after a beat — same feel as the cleaning worklist — while Enter
// and the button still fire it immediately.
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(reloadOrders, 300)
}

// Worklist status filter. "Selesai" is not a choice here: a job sent for review leaves the
// worklist for the review queue, and a closed one shows under Riwayat.
const filter = ref("all")
const startedOrders = computed(() => orders.value.filter((o) => o.status === "In Progress"))
const todoOrders = computed(() => orders.value.filter((o) => o.status !== "In Progress"))
const visibleOrders = computed(() => {
	if (filter.value === "started") return startedOrders.value
	if (filter.value === "todo") return todoOrders.value
	return orders.value
})
const FILTERS = computed(() => [
	{ key: "all", label: labels.mrFilterAll, count: orders.value.length },
	{ key: "todo", label: labels.mrFilterTodo, count: todoOrders.value.length },
	{ key: "started", label: labels.mrFilterStarted, count: startedOrders.value.length },
])
const emptyText = computed(() => {
	if (!orders.value.length) return labels.mrExecEmpty
	if (filter.value === "started") return labels.mrFilterEmptyStarted
	if (filter.value === "todo") return labels.mrFilterEmptyTodo
	return labels.mrExecEmpty
})

const headerCells = computed(() => {
	const h = order.value || {}
	return [
		{ label: labels.cleaningTankType, value: h.tank_type },
		{ label: labels.cleaningClient, value: h.client },
		{ label: labels.cleaningCapacity, value: h.capacity },
		{ label: labels.cleaningPrevCargo, value: h.previous_cargo },
		{ label: labels.cleaningTare, value: h.tare },
		{ label: labels.cleaningMgw, value: h.mgw },
	]
})

// Whether a detail fetch is in flight, tracked explicitly rather than derived from
// `route.query.o && !order`. The derived version flickers: submitting an order nulls `order`
// while the query is still set, and the screen would flash a skeleton on its way back to the
// worklist.
const detailPending = ref(false)
const detailFailed = ref(false)
const detailError = ref("")

const detailRes = cachedResource({
	url: "container_depot.ess.repairs.mr_order_detail",
	method: "GET",
	onSuccess(data) {
		detailPending.value = false
		detailFailed.value = false
		// Mute auto-save while the album is populated from the loaded order — otherwise
		// opening a job would immediately post back what it just read.
		suppressSave.value = true
		savedOk.value = false
		order.value = data
		used.value = (data.used_items || []).map((u) => reactive({ ...u, decision: u.decision || "Pending" }))
		workPhotos.value = (data.work_photos || []).map((p) => ({ ...p }))
		photoErr.value = ""
		nextTick(() => {
			suppressSave.value = false
		})
	},
	// The error stays on the page here rather than in a toast: a toast disappears, and the
	// operator would be left staring at a worklist wondering why their tap did nothing.
	onError(err) {
		detailPending.value = false
		detailFailed.value = true
		detailError.value = err?.messages?.[0] || err?.message || labels.error
	},
})

function fetchDetail(name) {
	detailPending.value = true
	detailFailed.value = false
	detailRes.fetch({ repair_order: name })
}
function retryDetail() {
	if (route.query.o) fetchDetail(route.query.o)
}

// The open order lives in the URL (?o=<name>) so a refresh restores the detail view.
// `pushedByTap` records whether *this* screen added that history entry: landing straight
// on ?o=… from a notification link added nothing, and popping then would walk the operator
// out of the app.
let pushedByTap = false
function openOrder(o) {
	pushedByTap = true
	router.push({ query: { o: o.name } })
}

watch(
	() => route.query.o,
	(o) => {
		if (o) {
			if (order.value?.name !== o) fetchDetail(o)
		} else {
			order.value = null
			detailPending.value = false
			detailFailed.value = false
		}
	},
	{ immediate: true }
)

// --- start (Pending -> In Progress) -----------------------------------------
//
// The status is flipped locally rather than re-fetched. The response carried nothing the
// screen needed except the new status, and waiting for it is what made "Mulai" impossible in
// a dead spot — which locked the technician out of the rest of the form.
//
// No `ref` on this row: starting is not finishing, so the order must stay in the worklist.
async function startRepair(name) {
	try {
		await send({
			url: "container_depot.ess.repairs.mr_start",
			payload: { repair_order: name },
		})
		toast.success(labels.mrStarted)
		return true
	} catch (e) {
		toast.error(e?.message || labels.error)
		return false
	}
}

async function startOrder(o) {
	if (await startRepair(o.name)) o.status = "In Progress"
}
async function startCurrent() {
	if (!order.value) return
	if (await startRepair(order.value.name)) order.value = { ...order.value, status: "In Progress" }
}

// --- evidence photos --------------------------------------------------------
//
// A photo goes up the moment it is taken and the album is saved straight after, so a phone
// that dies mid-repair loses nothing. `uploadPhoto` hands back a `local:` ref when the upload
// itself could not land; those are stripped from the auto-save (a `local:` string written
// into the table would be a broken image for ever) and carried by the submit instead, which
// goes through `send` and swaps them for real file_urls.

async function onPickPhotos(group, event) {
	const files = Array.from(event.target.files || [])
	event.target.value = "" // allow re-picking the same file
	if (!files.length) return
	photoErr.value = ""
	uploading.value = group.key
	try {
		for (const f of files) {
			workPhotos.value.push({
				photo: await uploadPhoto(f),
				// Both halves of the link: the ROW for precision (the same item can be on the
				// order twice) and the ITEM because that is what a human — and the owner
				// reading the print — actually recognises.
				used_item: group.line.name || null,
				item: group.line.item,
				caption: "",
			})
		}
		scheduleSave()
	} catch (e) {
		photoErr.value = labels.mrPhotoError
	} finally {
		uploading.value = null
	}
}

function removePhoto(row) {
	const i = workPhotos.value.indexOf(row)
	if (i >= 0) workPhotos.value.splice(i, 1)
	scheduleSave()
}

const saveRes = createResource({
	url: "container_depot.ess.repairs.mr_order_save",
	method: "POST",
	onSuccess() {
		savedOk.value = true
		flushPendingSave()
	},
	// An auto-save that could not reach the server is not worth a red toast — the operator is
	// mid-repair and the submit will carry the album anyway. Anything the server actively
	// REFUSED they do need to see.
	onError(err) {
		if (err?.response) photoErr.value = err?.messages?.[0] || err?.message || labels.error
		flushPendingSave()
	},
})

// Never two saves in flight at once. Each one replaces the whole album, so on a slow link an
// earlier response landing after a later one would restore photos the operator has since
// deleted. When the debounce fires mid-flight we remember it and re-arm from the handler.
let saveTimer = null
let resaveWanted = false

function flushPendingSave() {
	if (!resaveWanted) return
	resaveWanted = false
	scheduleSave()
}

function scheduleSave() {
	if (!order.value || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => {
		saveTimer = null
		if (saveRes.loading) {
			resaveWanted = true
			return
		}
		saveRes.fetch({
			repair_order: order.value.name,
			work_photos: JSON.stringify(workPhotos.value.filter((p) => !isLocalRef(p.photo))),
		})
	}, 700)
}

// --- send for review (In Progress -> Pending Review) ------------------------
//
// This is a hand-over, not a close: Desk checks the work and finalises it. Nothing moves in
// the warehouse either — the approved parts were issued back when the owner agreed.
//
// It still carries a request_id (`send` adds one): a lost response plus a naive retry would
// otherwise raise a second sign-off under a second id (see ess/idempotency.py).
const submitting = ref(false)

async function confirmSubmit() {
	const ok = await confirm({
		message: labels.mrSubmitReviewHint,
		confirmLabel: labels.mrSubmitReview,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) submitForReview()
}

// Used items aren't editable here — the estimate is owned by ERP — so this is just the
// submit flag.
async function submitForReview() {
	if (!order.value || submitting.value) return
	submitting.value = true
	const o = order.value
	try {
		if (saveTimer) {
			clearTimeout(saveTimer)
			saveTimer = null
		}
		await send({
			url: "container_depot.ess.repairs.mr_order_save",
			payload: {
				repair_order: o.name,
				// An array, not a JSON string: `send` has to walk the payload to find the
				// `local:` photo refs and swap them for real file_urls before it posts.
				work_photos: workPhotos.value,
				submit: 1,
			},
		})
		toast.success(labels.mrSubmittedReview, {
			title: o.repair_order_id || o.name,
		})
		order.value = null
		if (route.query.o) router.replace({ query: {} })
		reloadOrders()
		// It has left the worklist for the review queue — show it there rather than making
		// the operator wonder where their order went.
		reviewRes.reload()
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		submitting.value = false
	}
}

function backToList() {
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	suppressSave.value = true
	used.value = []
	workPhotos.value = []
	// A real Back, not another push: it drops the entry opening this order added (so the
	// phone's own Back does not walk straight back into it) and lets the router restore the
	// worklist to the row that was tapped.
	if (route.query.o) {
		if (pushedByTap) {
			pushedByTap = false
			router.back()
		} else router.replace({ query: {} })
	} else order.value = null
	reloadOrders()
}
</script>
