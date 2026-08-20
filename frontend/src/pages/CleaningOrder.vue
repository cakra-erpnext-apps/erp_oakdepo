<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.cleaningTitle }}
				</h1>
				<p v-if="order" class="truncate font-mono text-[11px] text-gray-500">
					{{ order.order_id }} · {{ order.container_no }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.cleaningOrdersHint }}</p>
			</div>
			<div class="flex shrink-0 items-center gap-2">
				<router-link v-if="!order" to="/cleaning/history" class="oak-btn oak-btn-secondary px-3 py-2">
					<Icon name="clock" :size="16" /> {{ labels.navHistory }}
				</router-link>
				<button v-if="order" class="oak-btn oak-btn-secondary px-3 py-2" @click="backToList">
					<Icon name="arrow-left" :size="16" /> {{ labels.cleaningBack }}
				</button>
			</div>
		</div>

		<!-- Submitted confirmation -->
		<section v-if="submitted" class="oak-card border-leaf-200 bg-leaf-50 p-4 space-y-2">
			<p class="font-bold text-leaf-700">
				<Icon name="check-circle" :size="18" /> {{ labels.cleaningSubmitted }}
			</p>
			<p class="font-mono text-sm text-gray-700">{{ submitted.order_id || submitted.name }}</p>
			<a :href="printUrl" target="_blank" rel="noopener" class="oak-btn oak-btn-secondary inline-flex px-3 py-2">
				<Icon name="printer" :size="16" /> {{ labels.cleaningPrint }}
			</a>
		</section>

		<!-- OPENING AN ORDER — placeholder while its detail is fetched. Without this the
		     worklist just sat there unchanged after a tap, which reads as a dead button. -->
		<SkeletonDetail v-if="detailPending" :cells="8" :sections="3" />

		<!-- The detail could not be fetched and there is no cached copy to fall back on. -->
		<section v-else-if="detailFailed" class="oak-card space-y-3 p-6 text-center">
			<span class="oak-icon-tile mx-auto h-12 w-12 bg-red-50 text-red-500">
				<Icon name="alert-triangle" :size="24" />
			</span>
			<p class="text-sm text-gray-600">{{ detailError }}</p>
			<div class="flex gap-2">
				<button class="oak-btn oak-btn-secondary flex-1" @click="backToList">{{ labels.cleaningBack }}</button>
				<button class="oak-btn oak-btn-primary flex-1" @click="retryDetail">{{ labels.retry }}</button>
			</div>
		</section>

		<!-- WORKLIST — same shape as the EIR worklist (/depot/eir): search, then Semua /
		     Belum / Dikerjakan toggles with counts, then a capped scroller of fixed-height
		     rows. Cleaning is triaged exactly the way EIR is, so it reads the same way; each
		     row leads with the tank and WHOSE it is, because that is what the operator sorts
		     the queue by. -->
		<section v-else-if="!order && !submitted" class="oak-section space-y-3">
			<div class="flex items-center gap-2">
				<Icon name="droplet" :size="16" class="text-brand-500" />
				<p class="oak-section-title">{{ labels.cleaningOrdersList }}</p>
			</div>
			<div class="flex gap-2">
				<input
					v-model="search"
					class="oak-input uppercase"
					:placeholder="labels.cleaningOrdersSearch"
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

			<!-- Belum / Dikerjakan split: a Pending order is "belum" until Mulai moves it to
			     In_Progress; a completed one leaves the worklist entirely (Riwayat). -->
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
									<Icon name="droplet" :size="16" />
								</span>
								<div class="min-w-0 flex-1">
									<p class="truncate font-semibold text-gray-900">
										{{ o.container_no || o.container }}<span v-if="o.container_principal" class="font-normal text-gray-500"> · {{ o.container_principal }}</span>
									</p>
									<!-- One subtitle line: what state it is in, when it has to be out, and
									     what it is. Ordered by urgency so the truncation eats the least
									     important half first. -->
									<p class="flex items-center gap-1.5 text-[11px]">
										<span v-if="o.status === 'In_Progress'" class="oak-chip shrink-0 bg-amber-100 text-amber-800">
											<Icon name="clock" :size="11" /> {{ labels.cleaningInProgress }}
										</span>
										<span v-if="o.target_lift_on" class="shrink-0 font-semibold" :class="liftClass(o.target_lift_on)">
											Lift-on {{ hMinus(o.target_lift_on) }}
										</span>
										<span class="truncate text-gray-400">
											<template v-if="o.service_count">{{ o.service_count }} {{ labels.cleaningServicesCount }}</template>
											<template v-else-if="o.cleaning_type">{{ o.cleaning_type }}</template>
											<template v-if="o.last_cargo"> · {{ o.last_cargo }}</template>
										</span>
									</p>
								</div>
							</button>
							<button
								v-if="o.status !== 'In_Progress'"
								class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs"
								@click.stop="startOrder(o)"
							>
								{{ labels.cleaningStart }}
							</button>
						</div>
					</li>
				</ul>
			</div>
			<p v-if="visibleOrders.length" class="text-center text-xs text-gray-400">
				{{ visibleOrders.length }} {{ labels.cleaningOrdersCount }}
			</p>
		</section>

		<!-- Sent for review (Pending Review) — the field is done, Admin Ops still has to check
		     and Submit on the Desk. Same section the EIR screen carries, and it stays visible
		     even when empty is false: an order sitting here is work nobody is doing. -->
		<section v-if="!order && !submitted && (reviewRes.loading || reviewItems.length)" class="oak-section space-y-3">
			<div class="flex items-center gap-2">
				<Icon name="clock" :size="16" class="text-sky-500" />
				<p class="oak-section-title">{{ labels.cleaningReviewList }}</p>
				<span v-if="reviewItems.length" class="oak-chip bg-sky-100 text-sky-700">{{ reviewItems.length }}</span>
			</div>
			<ul v-if="reviewRes.loading && !reviewItems.length" class="space-y-2">
				<li v-for="n in 2" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
			</ul>
			<p v-else-if="!reviewItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.cleaningReviewEmpty }}</p>
			<ul v-else class="divide-y divide-gray-100">
				<li v-for="r in reviewItems" :key="r.name">
					<div class="flex items-center gap-3 py-2.5">
						<button type="button" class="oak-press flex min-w-0 flex-1 items-center gap-3 text-left" @click="goFinished(r)">
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-sky-50 text-sky-600"><Icon name="clock" :size="16" /></span>
							<div class="min-w-0 flex-1">
								<p class="truncate font-semibold text-gray-900">
									{{ r.container_no || r.container }}<span v-if="r.container_principal" class="font-normal text-gray-500"> · {{ r.container_principal }}</span>
								</p>
								<p class="truncate text-[11px] text-gray-400">{{ r.order_id || r.name }}</p>
							</div>
							<span class="oak-chip shrink-0 bg-sky-100 text-sky-800">{{ labels.cleaningStatusPendingReview }}</span>
						</button>
						<!-- Pulling it back is the operator's own fix — no Admin Ops needed — so it
						     sits on the row rather than behind the detail. -->
						<button
							type="button"
							class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs"
							:disabled="withdrawRes.loading"
							@click.stop="withdrawReview(r)"
						>
							{{ labels.cleaningWithdrawReview }}
						</button>
					</div>
				</li>
			</ul>
		</section>

		<!-- Finished (Completed / Cancelled) — the last few, with the full log behind Riwayat. -->
		<section v-if="!order && !submitted" class="oak-section space-y-3">
			<div class="flex items-center justify-between gap-2">
				<div class="flex items-center gap-2">
					<Icon name="check-circle" :size="16" class="text-leaf-600" />
					<p class="oak-section-title">{{ labels.cleaningCompleteList }}</p>
				</div>
				<router-link to="/cleaning/history" class="oak-link text-sm">{{ labels.cleaningListMore }}</router-link>
			</div>
			<ul v-if="doneRes.loading && !doneItems.length" class="space-y-2">
				<li v-for="n in 3" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
			</ul>
			<p v-else-if="!doneItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.cleaningCompleteEmpty }}</p>
			<ul v-else class="divide-y divide-gray-100">
				<li v-for="r in doneItems" :key="r.name">
					<button type="button" class="oak-press flex w-full items-center gap-3 py-2.5 text-left" @click="goFinished(r)">
						<span class="oak-icon-tile h-9 w-9 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="droplet" :size="16" /></span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">
								{{ r.container_no || r.container }}<span v-if="r.container_principal" class="font-normal text-gray-500"> · {{ r.container_principal }}</span>
							</p>
							<p class="truncate text-xs text-gray-500">
								{{ r.order_id }}<span v-if="r.cleaning_end"> · {{ fmtDate(r.cleaning_end) }}</span>
							</p>
						</div>
						<span v-if="r.revision_requested" class="oak-chip shrink-0 bg-orange-100 text-orange-800">{{ labels.cleaningStatusRevision }}</span>
						<span class="oak-chip shrink-0" :class="r.status === 'Cancelled' ? 'bg-red-100 text-red-700' : 'bg-leaf-100 text-leaf-800'">
							{{ r.status === 'Cancelled' ? labels.cleaningStatusCancelled : labels.cleaningStatusCompleted }}
						</span>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</button>
				</li>
			</ul>
		</section>

		<!-- FORM -->
		<template v-if="order && !submitted">
			<!-- GATE: the order must be started before its detail is accessible. -->
			<section v-if="order.status !== 'In_Progress'" class="oak-card space-y-4 p-5 text-center">
				<span class="oak-icon-tile mx-auto h-14 w-14 bg-brand-50 text-brand-600"><Icon name="droplet" :size="26" /></span>
				<div class="space-y-1">
					<p class="font-bold text-gray-900">{{ order.container_no || order.container }}</p>
					<p class="font-mono text-xs text-gray-400">{{ order.order_id }}</p>
					<p class="text-sm text-gray-500">{{ labels.cleaningStartGate }}</p>
				</div>
				<button class="oak-btn oak-btn-primary w-full py-3 text-base" @click="startCurrent">
					{{ labels.cleaningStartFull }}
				</button>
			</section>

			<!-- Detail — read-only tank/method/cargo info; the operator only signs off. -->
			<template v-else>
			<!-- Cleaning method = the service(s) Admin Ops chose (read-only for the operator). -->
			<section class="oak-card p-4 space-y-3">
				<p class="oak-section-title">{{ labels.cleaningType }}</p>
				<div v-if="order.cleaning_services && order.cleaning_services.length" class="flex flex-wrap gap-1.5">
					<span
						v-for="s in order.cleaning_services"
						:key="s.item_code"
						class="inline-flex items-center rounded-full bg-brand-100 px-2.5 py-1 text-xs font-medium text-brand-700"
					>
						{{ s.item_name || s.item_code }}
					</span>
				</div>
				<p v-else class="text-sm text-gray-400">{{ labels.cleaningNoMethod }}</p>
			</section>

			<!-- Instruksi Cleaning — free text Admin Ops left on the order (read-only). -->
			<section v-if="order.cleaning_instructions" class="oak-card p-4 space-y-2">
				<p class="oak-section-title">{{ labels.cleaningInstructions }}</p>
				<p class="whitespace-pre-line text-sm text-gray-800">{{ order.cleaning_instructions }}</p>
			</section>

			<!-- Tank header -->
			<section class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.cleaningTankDetails }}</p>
				<dl class="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
					<div v-for="cell in headerCells" :key="cell.label" class="min-w-0">
						<dt class="text-xs text-gray-400">{{ cell.label }}</dt>
						<dd class="truncate font-medium text-gray-800">{{ cell.value || "—" }}</dd>
					</div>
				</dl>
				<p v-if="order.inspection" class="mt-2 font-mono text-[11px] text-gray-400">
					{{ labels.cleaningRefEir }}: {{ order.inspection }}
				</p>
				<p v-if="order.reff_doc" class="font-mono text-[11px] text-gray-400">
					{{ labels.reffDoc }}: {{ order.reff_doc }}
				</p>
			</section>

			<!-- Cargo history -->
			<section class="oak-card p-4">
				<p class="oak-section-title mb-2">{{ labels.cleaningCargoHistory }}</p>
				<ul v-if="order.cargo_history && order.cargo_history.length" class="space-y-1 text-sm">
					<li v-for="(h, i) in order.cargo_history" :key="i" class="flex justify-between gap-2">
						<span class="truncate font-medium text-gray-800">{{ h.cargo }}</span>
						<span class="shrink-0 text-xs text-gray-400">{{ h.date }}</span>
					</li>
				</ul>
				<p v-else class="text-sm text-gray-400">{{ labels.cleaningNoCargoHistory }}</p>
			</section>

			<!-- Foto QC -->
			<section class="oak-card p-4 space-y-3">
				<p class="oak-section-title">{{ labels.cleaningQcPhotos }}</p>

				<!-- Thumbnails (3-up, square tap-friendly tiles) + inline "add" tile -->
				<div class="grid grid-cols-3 gap-2">
					<div v-for="(p, i) in qcPhotos" :key="i" class="relative aspect-square">
						<img :src="photoSrc(p.photo)" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
						<button
							type="button"
							class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white shadow active:bg-black"
							:aria-label="labels.remove || 'Hapus'"
							@click="removeQcPhoto(i)"
						>
							<Icon name="x" :size="16" />
						</button>
					</div>

					<!-- Add tile — a full-size tap target that opens the camera on mobile -->
					<label
						class="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
					>
						<Icon v-if="photoUploading" name="loader" :size="22" class="animate-spin" />
						<template v-else>
							<Icon name="camera" :size="22" />
							<span class="text-xs font-medium">{{ labels.cleaningQcPhotoAdd }}</span>
						</template>
						<input
							type="file"
							accept="image/*"
							capture="environment"
							multiple
							class="hidden"
							:disabled="photoUploading"
							@change="onQcPhotos"
						/>
					</label>
				</div>
				<p v-if="!qcPhotos.length && !photoUploading" class="text-xs text-gray-400">{{ labels.cleaningQcPhotoEmpty }}</p>
			</section>

			<!-- Catatan -->
			<section class="oak-card p-4 space-y-2">
				<label class="oak-label">{{ labels.eirRemarks }}</label>
				<textarea v-model="remarks" rows="3" class="oak-input"></textarea>
			</section>

			<!-- Tanda Tangan -->
			<section class="oak-card p-4 space-y-2">
				<div class="flex items-center justify-between">
					<p class="oak-section-title">{{ labels.cleaningSignature }}</p>
					<button v-if="signatureUrl" type="button" class="oak-link text-sm" @click="startResign">
						{{ labels.cleaningResign }}
					</button>
				</div>
				<div v-if="signatureUrl && !signing">
					<img :src="photoSrc(signatureUrl)" class="h-28 w-full rounded-xl border border-gray-200 bg-white object-contain" />
				</div>
				<div v-else>
					<canvas
						ref="sigCanvas"
						class="h-28 w-full touch-none rounded-xl border border-dashed border-gray-300 bg-white"
						@pointerdown="sigDown"
						@pointermove="sigMove"
						@pointerup="sigUp"
						@pointerleave="sigUp"
					></canvas>
					<div class="mt-1 flex items-center justify-between text-xs text-gray-400">
						<span v-if="sigUploading">{{ labels.cleaningUploading }}</span>
						<span v-else-if="sigErr" class="text-red-600">{{ sigErr }}</span>
						<span v-else>{{ labels.signHint }}</span>
						<button type="button" class="text-gray-600 underline underline-offset-2" @click="clearSignature">
							{{ labels.clear }}
						</button>
					</div>
				</div>
			</section>

			<!-- Auto-save status (Catatan + Tanda Tangan persist on every edit) -->
			<p class="flex items-center gap-1.5 text-xs">
				<span v-if="saveRes.loading" class="text-gray-400">{{ labels.savingDraft }}</span>
				<span v-else-if="savedOk" class="inline-flex items-center gap-1 text-leaf-600">
					<Icon name="check" :size="13" /> {{ labels.draftSaved }}
				</span>
				<span v-else class="text-gray-400">{{ labels.autosaveHint }}</span>
			</p>

			<!-- Finalize — the order is already In_Progress inside this branch. -->
			<!-- Not gated on `saveRes.loading` — see EirInForm.vue: the finalise sends the whole
			     payload, so a slow autosave must never hold the button hostage. -->
			<button class="oak-btn oak-btn-primary w-full py-3" :disabled="submitting" @click="confirmComplete">
				<Icon v-if="submitting" name="loader" :size="18" class="animate-spin" />
				<span v-else>{{ labels.cleaningComplete }}</span>
			</button>
			<p class="text-center text-xs text-gray-400">{{ labels.cleaningCompleteHint }}</p>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { createResource } from "frappe-ui"
import { labels } from "@/utils/labels"
import { saveToast, toast } from "@/utils/toast"
import { confirm } from "@/utils/confirm"
import Icon from "@/components/Icon.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"
import { isLocalRef, photoSrc, send, uploadPhoto } from "@/data/send"

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
const submitted = ref(null)

// Auto-save (mirrors the EIR flow): debounced draft save on every edit.
let saveTimer = null
const savedOk = ref(false) // last auto-save succeeded
const suppressSave = ref(false) // mute auto-save while a draft is being loaded

// The operator only signs off now: Catatan (remarks) + Tanda Tangan (signature). The cleaning
// method(s) are chosen upstream by Admin Ops and shown read-only.
const remarks = ref("")
// QC photo list (uploaded file_urls).
const qcPhotos = ref([])
const photoUploading = ref(false)

const printUrl = computed(() =>
	submitted.value
		? `/api/method/frappe.utils.print_format.download_pdf?doctype=Cleaning%20Order&name=${encodeURIComponent(
				submitted.value.name
		  )}&format=Cleaning%20Order%20Format&no_letterhead=1`
		: "#"
)

const ordersRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_orders",
	method: "GET",
	auto: true,
	onSuccess: (data) => (allOrders.value = data.items || []),
})

// How many finished orders the landing shows before "Lihat semua" takes over.
const LANDING_LIMIT = 5

// "Diajukan Review" — orders finished in the field, waiting for Admin Ops to check and
// Submit on the Desk. Opened read-only like a finished one; withdrawable from the row.
const reviewItems = ref([])
const reviewRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_pending_review",
	method: "GET",
	auto: true,
	onSuccess: (data) => (reviewItems.value = data.items || []),
})

const doneItems = ref([])
const doneRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_history",
	method: "GET",
	makeParams: () => ({ page_length: LANDING_LIMIT }),
	auto: true,
	onSuccess: (data) => (doneItems.value = data.items || []),
})

// Finished (or field-done) work has no editable form to open — the Riwayat detail takes an
// ?open= deep link and fetches the order straight from the server.
function goFinished(r) {
	router.push({ path: "/cleaning/history", query: { open: r.name } })
}

const withdrawRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_withdraw_review",
	method: "POST",
	onSuccess: () => {
		toast.success(labels.cleaningWithdrawReviewDone)
		reloadOrders()
		reviewRes.reload()
	},
	onError: (e) => toast.error(e?.messages?.[0] || e?.message || labels.error),
})
function withdrawReview(r) {
	withdrawRes.submit({ cleaning_order: r.name })
}

// An order whose sign-off is already queued is finished as far as the operator is concerned.
// Leaving it in the list — which it will be, because the server has not heard about it yet —
// invites them to do the whole job a second time.
const orders = computed(() => allOrders.value)

function reloadOrders() {
	const s = search.value.trim()
	ordersRes.fetch(s ? { search: s } : {})
}

// Typing searches on its own after a beat — same feel as the EIR worklist — while Enter and
// the button still fire it immediately.
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(reloadOrders, 300)
}

// Worklist status filter. "Selesai" is not a choice here: a submitted cleaning leaves the
// worklist entirely and shows under Riwayat.
const filter = ref("all")
const startedOrders = computed(() => orders.value.filter((o) => o.status === "In_Progress"))
const todoOrders = computed(() => orders.value.filter((o) => o.status !== "In_Progress"))
const visibleOrders = computed(() => {
	if (filter.value === "started") return startedOrders.value
	if (filter.value === "todo") return todoOrders.value
	return orders.value
})
const FILTERS = computed(() => [
	{ key: "all", label: labels.cleaningFilterAll, count: orders.value.length },
	{ key: "todo", label: labels.cleaningFilterTodo, count: todoOrders.value.length },
	{ key: "started", label: labels.cleaningFilterStarted, count: startedOrders.value.length },
])
const emptyText = computed(() => {
	if (!orders.value.length) return labels.cleaningOrdersEmpty
	if (filter.value === "started") return labels.cleaningFilterEmptyStarted
	if (filter.value === "todo") return labels.cleaningFilterEmptyTodo
	return labels.cleaningOrdersEmpty
})


const headerCells = computed(() => {
	const h = order.value || {}
	return [
		{ label: labels.cleaningTankType, value: h.tank_type },
		{ label: labels.cleaningClient, value: h.client },
		{ label: labels.cleaningCapacity, value: h.capacity },
		{ label: labels.cleaningTare, value: h.tare },
		{ label: labels.cleaningMgw, value: h.mgw },
		{ label: labels.cleaningPrevCargo, value: h.previous_cargo },
		{ label: labels.cleaningMfgDate, value: h.date_of_manufacture },
		{ label: labels.cleaningLastTest, value: h.last_test_date },
	]
})

// Whether a detail fetch is in flight, tracked explicitly rather than derived from
// `route.query.o && !order`. The derived version flickers: completing an order nulls `order`
// while the query is still set, and the screen would flash a skeleton on its way back to the
// worklist.
const detailPending = ref(false)
const detailFailed = ref(false)
const detailError = ref("")

const detailRes = cachedResource({
	url: "container_depot.ess.cleaning.cleaning_order_detail",
	method: "GET",
	onSuccess(data) {
		detailPending.value = false
		detailFailed.value = false
		// Mute auto-save while we populate the form from the loaded order.
		suppressSave.value = true
		savedOk.value = false
		order.value = data
		remarks.value = data.remarks || ""
		signatureUrl.value = data.signature || ""
		qcPhotos.value = (data.qc_photos || []).map((p) => ({ ...p }))
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

// The open order lives in the URL (?o=<name>) so a refresh restores the detail view
// instead of dropping back to the worklist. `pushedByTap` records whether *this* screen
// added that history entry: landing straight on ?o=… from a notification link added
// nothing, and popping then would walk the operator out of the app.
let pushedByTap = false
function openOrder(o) {
	pushedByTap = true
	router.push({ query: { o: o.name } })
}

function fetchDetail(name) {
	detailPending.value = true
	detailFailed.value = false
	detailRes.fetch({ cleaning_order: name })
}
function retryDetail() {
	if (route.query.o) fetchDetail(route.query.o)
}

watch(
	() => route.query.o,
	(o) => {
		if (o) {
			if (order.value?.name !== o) {
				submitted.value = null
				fetchDetail(o)
			}
		} else {
			order.value = null
			detailPending.value = false
			detailFailed.value = false
		}
	},
	{ immediate: true }
)

// Mulai Cleaning (worklist or in-form).
//
// The status is flipped locally rather than re-fetched. The
// response carried nothing the form needed except the new status, so there is no reason to
// wait for it — and waiting is what made "Mulai" impossible in a dead spot, which locked the
// operator out of the whole form.
//
// No `ref` on this row: starting is not finishing, and the order must stay in the worklist.
async function startCleaning(name) {
	try {
		await send({
			url: "container_depot.ess.cleaning.cleaning_start",
			payload: { cleaning_order: name },
		})
		toast.success(labels.cleaningStarted)
		return true
	} catch (e) {
		toast.error(e?.message || labels.error)
		return false
	}
}

async function startOrder(o) {
	if (await startCleaning(o.name)) o.status = "In_Progress"
}
async function startCurrent() {
	if (!order.value) return
	if (await startCleaning(order.value.name)) order.value = { ...order.value, status: "In_Progress" }
}

// Server-side autosave only. The finalise has its own call (see submitCleaning), so this
// resource never sees submit=1 and never has to deal with the finalized branch.
const saveRes = createResource({
	url: "container_depot.ess.cleaning.cleaning_order_save",
	method: "POST",
	onSuccess() {
		savedOk.value = true
		saveToast.done()
		flushPendingSave()
	},
	// An autosave that could not reach the server is not worth a red toast — the operator is
	// mid-form, the local draft has the data, and the finalise will carry it. Anything the
	// server actively refused, they do need to see.
	// The busy toast is cleared either way — `fail("")` just takes the slot back.
	onError(err) {
		saveToast.fail(err?.response ? err?.messages?.[0] || err?.message || labels.error : "")
		flushPendingSave()
	},
})

// Never two autosaves in flight at once. Each one writes the whole document, so on a slow
// link an earlier response landing after a later one restores stale text over what the
// operator has since typed. When the debounce fires mid-flight we remember the edit and
// re-arm from the response handler instead of stacking a second POST.
let resaveWanted = false

/** Called when a save settles: if edits arrived while it flew, start the debounce again. */
function flushPendingSave() {
	if (!resaveWanted) return
	resaveWanted = false
	scheduleSave()
}

// Debounced auto-save on every edit (mirrors EIR): only while an unfinished order is open.
function scheduleSave() {
	if (!order.value || order.value.docstatus === 1 || suppressSave.value) return
	savedOk.value = false
	if (saveTimer) clearTimeout(saveTimer)
	saveTimer = setTimeout(() => {
		saveTimer = null
		if (saveRes.loading) {
			resaveWanted = true
			return
		}
		save(false)
	}, 700)
}

// Finalize (Selesaikan) asks for an explicit confirmation first.
async function confirmComplete() {
	const ok = await confirm({
		title: labels.confirmSubmitTitle,
		message: labels.confirmSubmitMessage,
		confirmLabel: labels.confirmSubmitYes,
		cancelLabel: labels.confirmCancel,
	})
	if (ok) save(true)
}

function payload(submit) {
	return {
		cleaning_order: order.value.name,
		remarks: remarks.value || undefined,
		signature: signatureUrl.value || undefined,
		// An array, not a JSON string: `send` has to walk the payload to find the
		// `local:` photo references and swap them for real file_urls.
		qc_photos: qcPhotos.value.filter((p) => p.photo),
		submit: submit ? 1 : 0,
	}
}


function save(submit) {
	if (!order.value) return
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	if (submit) {
		submitCleaning()
		return
	}
	const p = payload(false)
	saveToast.start()
	// Strip anything not yet uploaded: a `local:` string written into a QC photo
	// row would be a broken image for ever. Those travel with the finalise instead.
	saveRes.fetch({
		...p,
		signature: isLocalRef(p.signature) ? undefined : p.signature,
		qc_photos: JSON.stringify(p.qc_photos.filter((x) => !isLocalRef(x.photo))),
	})
}

// Held while the send is in flight. `send` waits for the server (and for
// any QC photos to upload), so the button is live for a real second or two — long enough for
// an impatient second tap to raise a second sign-off under a second request_id.
const submitting = ref(false)

/** Hand the finished sign-off to `send`: photos first, then the document, then wait. */
async function submitCleaning() {
	const o = order.value
	if (submitting.value) return
	submitting.value = true
	try {
		await send({
			// Cleared by the queue once the save has actually landed — not here. If this row
			// comes back refused (the order closed on the Desk meanwhile), the draft is what
			// still holds the photos and the remarks.
			url: "container_depot.ess.cleaning.cleaning_order_save",
			payload: payload(true),
		})
		toast.success(labels.cleaningSubmitted, {
			title: o.order_id || o.name,
		})
		submitted.value = null
		resetForm()
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

// --- QC photo handlers ------------------------------------------------------
function removeQcPhoto(i) {
	qcPhotos.value.splice(i, 1)
}
async function onQcPhotos(e) {
	const files = Array.from(e.target.files || [])
	e.target.value = "" // allow re-picking the same file
	if (!files.length) return
	photoUploading.value = true
	try {
		for (const f of files) {
			const url = await uploadFile(f)
			qcPhotos.value.push({ photo: url, caption: "" })
		}
	} catch (err) {
		toast.error(labels.error)
	} finally {
		photoUploading.value = false
	}
}

function backToList() {
	submitted.value = null
	resetForm()
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

function resetForm() {
	// Clearing the form must never trigger an auto-save of the emptied fields.
	if (saveTimer) {
		clearTimeout(saveTimer)
		saveTimer = null
	}
	suppressSave.value = true
	savedOk.value = false
	remarks.value = ""
	signatureUrl.value = ""
	signing.value = false
	qcPhotos.value = []
}

// --- file upload + virtual signature pad ------------------------------------

/**
 * Take a picked photo and hand back a reference the form can hold onto.
 *
 * It goes up straight away, so the autosave that follows puts a real file_url on the order
 * and the QC evidence survives a reload. When the link is down it is parked instead and the
 * `local:` reference travels through the form exactly like a URL, until `send` uploads it on
 * Selesaikan (see data/send.js).
 */
async function uploadFile(file) {
	return uploadPhoto(file)
}

const sigCanvas = ref(null)
const signatureUrl = ref("")
const signing = ref(false)
const sigUploading = ref(false)
const sigErr = ref("")
let sigCtx = null
let sigDrawing = false
let sigHasInk = false
let sigTimer = null

function sigCtxInit() {
	const c = sigCanvas.value
	if (!c) return null
	if (sigCtx && sigCtx.canvas === c) return sigCtx
	const ratio = window.devicePixelRatio || 1
	c.width = c.clientWidth * ratio
	c.height = c.clientHeight * ratio
	const ctx = c.getContext("2d")
	ctx.scale(ratio, ratio)
	ctx.lineWidth = 2
	ctx.lineCap = "round"
	ctx.lineJoin = "round"
	ctx.strokeStyle = "#111827"
	sigCtx = ctx
	return ctx
}

function sigPos(e) {
	const r = sigCanvas.value.getBoundingClientRect()
	return { x: e.clientX - r.left, y: e.clientY - r.top }
}

function sigDown(e) {
	const ctx = sigCtxInit()
	if (!ctx) return
	sigDrawing = true
	const p = sigPos(e)
	ctx.beginPath()
	ctx.moveTo(p.x, p.y)
	sigCanvas.value.setPointerCapture?.(e.pointerId)
}

function sigMove(e) {
	if (!sigDrawing || !sigCtx) return
	const p = sigPos(e)
	sigCtx.lineTo(p.x, p.y)
	sigCtx.stroke()
	sigHasInk = true
}

function sigUp() {
	if (!sigDrawing) return
	sigDrawing = false
	if (!sigHasInk) return
	if (sigTimer) clearTimeout(sigTimer)
	sigTimer = setTimeout(uploadSignature, 600)
}

async function uploadSignature() {
	const c = sigCanvas.value
	if (!c || !sigHasInk) return
	sigErr.value = ""
	sigUploading.value = true
	try {
		const blob = await new Promise((res) => c.toBlob(res, "image/png"))
		signatureUrl.value = await uploadFile(new File([blob], "cleaning-signature.png", { type: "image/png" }))
		signing.value = false
	} catch (e) {
		sigErr.value = labels.signatureError
	} finally {
		sigUploading.value = false
	}
}

function clearSignature() {
	if (sigTimer) clearTimeout(sigTimer)
	const ctx = sigCtxInit()
	if (ctx && sigCanvas.value) ctx.clearRect(0, 0, sigCanvas.value.width, sigCanvas.value.height)
	sigHasInk = false
	signatureUrl.value = ""
}

function startResign() {
	signatureUrl.value = ""
	signing.value = true
	sigHasInk = false
	sigCtx = null
	nextTick(sigCtxInit)
}

// Auto-save on every edit: Catatan (remarks) + Tanda Tangan (signature) + QC/material.
watch([remarks, signatureUrl], scheduleSave)
watch(qcPhotos, scheduleSave, { deep: true })
</script>
