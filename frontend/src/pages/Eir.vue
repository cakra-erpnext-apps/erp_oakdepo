<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- =================== FORM (In or Out) =================== -->
		<template v-if="activeInspection && activeType">
			<!-- Queue navigator: only when this account is working more than one EIR. Lets the
			     surveyor jump ◀ / ▶ between the EIRs they started without going back to the list;
			     submitting one auto-advances to the next (see onSubmitted / onBack). -->
			<!-- Sticky so the ◀ / ▶ controls stay reachable while scrolling a long EIR form.
			     Pinned just below the app header, whose real height App.vue publishes as
			     --oak-header-h. Its OWN height goes out as --oak-nav-h so the EIR form's
			     header parks under it instead of landing on the same strip. -->
			<div
				v-if="navQueue.length > 1 && activeIndex !== -1"
				ref="navBar"
				class="oak-card oak-subheader space-y-2 p-2"
			>
				<div class="flex items-center justify-between gap-2">
					<button class="oak-btn oak-btn-secondary px-3 py-2" @click="goRel(-1)">
						<Icon name="chevron-left" :size="16" /> {{ labels.eirNavPrev }}
					</button>
					<div class="flex min-w-0 flex-col items-center leading-tight">
						<span class="text-[11px] font-semibold text-gray-400">
							{{ labels.eirBadge }} {{ activeIndex + 1 }} / {{ navQueue.length }}
						</span>
						<span class="max-w-[9rem] truncate text-sm font-bold text-gray-800">
							{{ activeItem?.container_no || activeItem?.container || "—" }}
						</span>
					</div>
					<button class="oak-btn oak-btn-secondary px-3 py-2" @click="goRel(1)">
						{{ labels.eirNavNext }} <Icon name="chevron-right" :size="16" />
					</button>
				</div>
				<button class="oak-link mx-auto block text-xs" @click="clearBatch">{{ labels.eirBatchExit }}</button>
			</div>
			<component
				:is="activeType === 'EIR-Out' ? EirOutForm : EirInForm"
				:key="activeInspection + activeType"
				:inspection="activeInspection"
				@back="onBack"
				@submitted="onSubmitted"
			/>
		</template>
		<!-- ?e= without ?t= (hand-typed / shared link): the worklist is still resolving
		     which direction this EIR is. Rendering the wrong form would call the wrong
		     endpoint, so wait rather than guess. -->
		<div v-else-if="activeInspection" class="oak-section space-y-2">
			<div class="oak-skeleton h-6 w-1/2 rounded-md"></div>
			<div class="oak-skeleton h-24 rounded-xl"></div>
		</div>

		<!-- =================== WORKLIST + LANDING =================== -->
		<template v-else>
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div class="flex items-center gap-2">
					<span class="oak-icon-tile h-9 w-9 bg-leaf-50 text-leaf-600"><Icon name="clipboard" :size="20" /></span>
					<div class="min-w-0">
						<h1 class="text-lg font-extrabold leading-tight tracking-tight">{{ labels.eirTitle }}</h1>
						<p class="truncate text-xs text-gray-500">{{ labels.eirCombinedSubtitle }}</p>
					</div>
				</div>
				<div class="flex items-center gap-2">
					<router-link to="/eir/sort" class="oak-btn oak-btn-secondary px-3 py-2">
						<Icon name="layers" :size="16" /> {{ labels.eirSortOpen }}
					</router-link>
					<router-link to="/eir/history" class="oak-btn oak-btn-secondary px-3 py-2">
						<Icon name="clock" :size="16" /> {{ labels.eirHistory }}
					</router-link>
				</div>
			</div>

			<!-- Pending worklist (In + Out combined, badge per row). Capped to ~5 rows tall,
			     scrolls internally so a long queue never runs far down the page. -->
			<section class="oak-section space-y-3">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						<Icon name="clipboard" :size="16" class="text-amber-500" />
						<p class="oak-section-title">{{ labels.eirPendingList }}</p>
					</div>
					<!-- Batch mode: pick several EIRs, then "Mulai" starts them all under this
					     account so the navigator/auto-advance can walk them (started-by-me). -->
					<button
						class="oak-btn px-3 py-1.5 text-xs"
						:class="selectMode ? 'oak-btn-primary' : 'oak-btn-secondary'"
						@click="toggleSelectMode"
					>
						<Icon :name="selectMode ? 'x' : 'check-square'" :size="14" />
						{{ selectMode ? labels.eirSelectCancel : labels.eirSelect }}
					</button>
				</div>
				<!-- Dua baris kontrol, bukan tiga. Sebelumnya: kotak cari + tombol cari, lalu
				     satu grid tombol tebal untuk status, lalu satu grid tombol tebal lagi untuk
				     arah — tiga baris penuh sebelum satu pun data terlihat, yang di layar HP
				     berarti daftarnya mulai di bawah lipatan. Ikon cari masuk ke dalam
				     kotaknya (tombol terpisah itu tidak pernah perlu: pencariannya sudah jalan
				     sendiri 300 ms setelah ketikan berhenti), dan arah jadi segmented ringkas
				     di sebelahnya. -->
				<div class="flex items-center gap-2">
					<div class="relative min-w-0 flex-1">
						<Icon name="search" :size="16" class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
						<input
							v-model.trim="search"
							type="text"
							:placeholder="labels.eirPendingSearch"
							class="oak-input pl-8 uppercase"
							@input="onSearchInput"
						/>
					</div>
					<!-- Masuk / Keluar: pekerjaan yang berbeda (tank datang vs pergi), sering
					     dikerjakan berkelompok. Tanpa angka — pil status di bawahnya sudah
					     menghitung ulang untuk arah yang sedang dipilih, jadi "Semua 3" di sana
					     adalah jumlah untuk arah ini; dua tempat menampilkan angka yang sama
					     hanya menambah yang harus dibaca. -->
					<div class="flex shrink-0 rounded-lg border border-gray-200 bg-gray-50 p-0.5">
						<button
							v-for="f in DIR_FILTERS"
							:key="f.key"
							class="rounded-md px-2.5 py-1.5 text-[11px] font-bold transition"
							:class="dirFilter === f.key ? 'bg-white text-brand-700 shadow-sm' : 'text-gray-500'"
							@click="dirFilter = f.key"
						>
							{{ f.label }}
						</button>
					</div>
				</div>

				<!-- Belum / Dikerjakan. A draft EIR is "belum" until Mulai stamps
				     work_started_on; submitted ones move to the Selesai section below. Pil,
				     bukan tombol selebar sepertiga layar: ini saringan, bukan aksi utama
				     halaman, dan berat visualnya dulu menyaingi daftarnya sendiri. -->
				<div class="flex flex-wrap items-center gap-1.5">
					<span class="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{{ labels.eirFilterStatus }}</span>
					<button
						v-for="f in FILTERS"
						:key="f.key"
						class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold transition active:scale-[0.97]"
						:class="filter === f.key ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-gray-200 bg-white text-gray-600'"
						@click="filter = f.key"
					>
						{{ f.label }}
						<span
							class="rounded-full px-1.5 text-[10px] font-bold"
							:class="filter === f.key ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-500'"
						>{{ f.count }}</span>
					</button>
				</div>

				<ul v-if="loadingPending && !pendingItems.length" class="space-y-2">
					<li v-for="n in 4" :key="n" class="oak-skeleton h-14 rounded-xl"></li>
				</ul>
				<div v-else-if="!visibleItems.length" class="flex flex-col items-center gap-1 py-6 text-center">
					<span class="oak-icon-tile h-11 w-11 bg-gray-100 text-gray-300"><Icon name="inbox" :size="22" /></span>
					<p class="text-sm font-semibold text-gray-500">{{ emptyText }}</p>
					<!-- Kalimat kedua hanya untuk kosong yang sebenar-benarnya: kalau daftarnya
					     kosong karena saringan, "dibuat otomatis dari bon" menjawab pertanyaan
					     yang tidak sedang ditanya. -->
					<p v-if="!pendingItems.length" class="text-xs text-gray-400">{{ labels.eirPendingEmptyHint }}</p>
				</div>
				<!-- Every draft is listed; the scroller reveals about 5 rows and the rest
			     scroll. Rows are no longer a fixed 60px: the EIR number moved onto the row
			     (see below), so the height follows the content instead of clipping it. -->
				<div v-else class="max-h-[340px] overflow-y-auto overscroll-contain">
					<ul class="divide-y divide-gray-100">
						<li v-for="r in visibleItems" :key="r.name">
							<button class="flex min-h-[64px] w-full items-center gap-3 py-2 text-left" @click="rowClick(r)">
								<!-- Select-mode tick box (replaces navigation while picking a batch). -->
								<span
									v-if="selectMode"
									class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border"
									:class="selected.has(r.name) ? 'border-brand-500 bg-brand-500 text-white' : 'border-gray-300'"
								>
									<Icon v-if="selected.has(r.name)" name="check" :size="14" />
								</span>
								<span class="oak-icon-tile h-9 w-9 shrink-0" :class="r._type === 'EIR-Out' ? 'bg-brand-50 text-brand-600' : 'bg-amber-50 text-amber-600'">
									<Icon :name="r._type === 'EIR-Out' ? 'log-out' : 'clipboard'" :size="16" />
								</span>
								<div class="min-w-0 flex-1">
									<!-- Nomor tank memiliki barisnya sendiri, nomor EIR-nya menepi ke
									     kanan: keduanya identitas, tapi yang di-scan mata cuma yang
									     kiri — dan nomor EIR yang dulu tidak ada di baris ini adalah
									     satu-satunya cara mencocokkan layar dengan kertas. -->
									<div class="flex items-baseline justify-between gap-2">
										<p class="truncate font-bold text-gray-900">{{ r.container_no || r.container }}</p>
										<span class="shrink-0 font-mono text-[10px] text-gray-400">{{ r.inspection_id || r.name }}</span>
									</div>
									<p v-if="r.container_principal || r.tank_status" class="truncate text-[11px] text-gray-500">
										{{ [r.container_principal, r.tank_status].filter(Boolean).join(" · ") }}
									</p>
									<!-- Baris chip: apa yang mendesak dan siapa yang sudah memegangnya. -->
									<p class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
										<span v-if="r.work_started_on" class="oak-chip shrink-0 bg-amber-100 text-amber-800">
											<Icon name="clock" :size="11" /> {{ labels.eirChipStarted }}
										</span>
										<LiftOnBadge :survey="r.target_survey_on" :target="r.target_lift_on" />
										<span v-if="r.referred_voucher" class="truncate font-mono text-gray-500">{{ r.referred_voucher }}</span>
									</p>
								</div>
								<span
									class="oak-chip shrink-0"
									:class="r._type === 'EIR-Out' ? 'bg-brand-100 text-brand-700' : 'bg-leaf-100 text-leaf-800'"
								>
									<Icon :name="r._type === 'EIR-Out' ? 'arrow-up-right' : 'arrow-down-left'" :size="11" />
									{{ r._type === 'EIR-Out' ? labels.eirBadgeOut : labels.eirBadgeIn }}
								</span>
							</button>
						</li>
					</ul>
				</div>
				<p v-if="visibleItems.length && !selectMode" class="text-center text-xs text-gray-400">{{ visibleItems.length }} {{ labels.eirPendingCount }}</p>
				<button
					v-if="selectMode"
					class="oak-btn oak-btn-primary w-full py-2.5"
					:disabled="!selected.size"
					@click="openBatch"
				>
					<Icon name="arrow-right" :size="16" /> {{ labels.eirBatchOpen }} <template v-if="selected.size">({{ selected.size }})</template>
				</button>
				<p v-if="fetchError" class="flex items-center gap-1.5 text-sm text-red-600">
					<Icon name="alert-circle" :size="15" /> {{ fetchError }}
				</p>
			</section>

			<!-- Sent for review (Pending Review) — field operator submitted, awaiting Admin
			     Ops's Desk Submit. Read-only detail, same as the completed list. Hidden when
			     empty so the landing stays clean for accounts that don't send-for-review. -->
			<section v-if="reviewRes.loading || reviewItems.length" class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="clock" :size="16" class="text-sky-500" />
					<p class="oak-section-title">{{ labels.eirReviewList }}</p>
					<span v-if="reviewItems.length" class="oak-chip bg-sky-100 text-sky-700">{{ reviewItems.length }}</span>
				</div>
				<ul v-if="reviewRes.loading && !reviewItems.length" class="space-y-2">
					<li v-for="n in 2" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
				</ul>
				<p v-else-if="!reviewItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.eirReviewEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="r in reviewItems" :key="r.name">
						<button type="button" class="oak-press flex w-full items-center gap-3 py-2.5 text-left" @click="goCompleted(r)">
							<!-- Inisial orangnya, bukan ikon jam yang sama di setiap baris. Daftar
							     ini branch-scoped: barisnya bisa milik siapa saja, dan "punya siapa
							     yang ini" adalah hal pertama yang ditanya sebelum menariknya
							     kembali. Jatuh balik ke ikon kalau EIR-nya belum berpemilik. -->
							<span class="oak-icon-tile h-9 w-9 shrink-0 bg-sky-50 text-[11px] font-extrabold text-sky-700">
								<template v-if="initials(r.inspector_name)">{{ initials(r.inspector_name) }}</template>
								<Icon v-else name="clock" :size="16" />
							</span>
							<div class="min-w-0 flex-1">
								<div class="flex items-baseline justify-between gap-2">
									<p class="truncate font-bold text-gray-900">{{ r.container_no || r.container }}</p>
									<span class="shrink-0 font-mono text-[10px] text-gray-400">{{ r.inspection_id || r.name }}</span>
								</div>
								<p class="truncate text-[11px] text-gray-500">
									{{ [r.container_principal, r.inspection_type, r.tank_status].filter(Boolean).join(" · ") }}
								</p>
								<p class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
									<span class="oak-chip shrink-0 bg-sky-100 text-sky-800">{{ labels.eirStatusPendingReview }}</span>
									<LiftOnBadge :survey="r.target_survey_on" :target="r.target_lift_on" />
								</p>
								<!-- Sudah berapa lama menunggu, dan pada siapa. Sebuah antrean review
								     tanpa umur tidak bisa dibedakan mana yang baru masuk dan mana yang
								     tertinggal sejak kemarin. -->
								<p v-if="r.inspector_name || r.modified" class="mt-1 flex items-center gap-1 truncate text-[11px] text-gray-400">
									<Icon name="clock" :size="11" class="shrink-0" />
									{{ [since(r.modified), r.inspector_name].filter(Boolean).join(" · ") }}
								</p>
							</div>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</button>
					</li>
				</ul>
			</section>

			<!-- Completed (submitted) EIRs — In & Out -->
			<section class="oak-section space-y-3">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2">
						<Icon name="check-circle" :size="16" class="text-leaf-600" />
						<p class="oak-section-title">{{ labels.eirCompleteList }}</p>
					</div>
					<router-link to="/eir/history" class="oak-link text-sm">{{ labels.eirListMore }}</router-link>
				</div>
				<ul v-if="doneRes.loading && !doneItems.length" class="space-y-2">
					<li v-for="n in 3" :key="n" class="oak-skeleton h-12 rounded-xl"></li>
				</ul>
				<p v-else-if="!doneItems.length" class="py-2 text-center text-sm text-gray-400">{{ labels.eirCompleteEmpty }}</p>
				<ul v-else class="divide-y divide-gray-100">
					<li v-for="r in doneItems" :key="r.name">
						<button type="button" class="oak-press flex w-full items-center gap-3 py-2.5 text-left" @click="goCompleted(r)">
							<span class="oak-icon-tile h-9 w-9 shrink-0" :class="r.inspection_type === 'EIR-Out' ? 'bg-brand-50 text-brand-600' : 'bg-leaf-50 text-leaf-600'">
								<Icon :name="r.inspection_type === 'EIR-Out' ? 'arrow-up-right' : 'arrow-down-left'" :size="16" />
							</span>
							<div class="min-w-0 flex-1">
								<div class="flex items-baseline justify-between gap-2">
									<p class="truncate font-bold text-gray-900">{{ r.container_no || r.container }}</p>
									<span class="shrink-0 font-mono text-[10px] text-gray-400">{{ r.inspection_id || r.name }}</span>
								</div>
								<p class="truncate text-[11px] text-gray-500">
									{{ [r.container_principal, r.inspection_type, r.tank_status].filter(Boolean).join(" · ") }}
								</p>
								<p v-if="r.inspector_name || r.modified" class="mt-0.5 flex items-center gap-1 truncate text-[11px] text-gray-400">
									<Icon name="clock" :size="11" class="shrink-0" />
									{{ [since(r.modified), r.inspector_name].filter(Boolean).join(" · ") }}
								</p>
							</div>
							<span v-if="r.revision_requested" class="oak-chip shrink-0 bg-orange-100 text-orange-800">{{ labels.eirStatusRevision }}</span>
							<span class="oak-chip shrink-0" :class="r.inspection_type === 'EIR-Out' ? 'bg-brand-100 text-brand-700' : 'bg-leaf-100 text-leaf-800'">
								<Icon :name="r.inspection_type === 'EIR-Out' ? 'arrow-up-right' : 'arrow-down-left'" :size="11" />
								{{ r.inspection_type === 'EIR-Out' ? labels.eirBadgeOut : labels.eirBadgeIn }}
							</span>
							<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
						</button>
					</li>
				</ul>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { since } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import { cachedResource } from "@/data/cache"
import { keepScrollForNextNavigation } from "@/router"
import EirInForm from "@/pages/EirInForm.vue"
import EirOutForm from "@/pages/EirOutForm.vue"

const route = useRoute()
const router = useRouter()

// "Budi Santoso" -> "BS". Dipakai sebagai penanda baris, bukan sebagai identitas: nama
// lengkapnya tetap tertulis di baris waktu tepat di bawahnya, jadi inisial yang bertabrakan
// antar dua orang tidak menyesatkan siapa pun — ia cuma membuat baris milik orang yang sama
// terlihat berkelompok saat daftar di-scroll.
function initials(name) {
	const parts = String(name || "").trim().split(/\s+/).filter(Boolean)
	if (!parts.length) return ""
	return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase()
}

// One EIR menu for both directions. The worklist below merges pending EIR-In and EIR-Out
// (each row badged by type); tapping opens the matching form component.
//
// The open EIR lives in the URL (?e=<name>&t=in|out) — same contract as CleaningOrder's
// ?o= — so a refresh restores the form instead of dropping back to the worklist. The
// direction rides along because the two forms hit different endpoints, so it must
// survive the reload too.
const activeInspection = computed(() => route.query.e || null)
const activeType = computed(() => {
	if (route.query.t === "out") return "EIR-Out"
	if (route.query.t === "in") return "EIR-In"
	// No ?t (hand-typed / shared link): recover the direction from the worklist rather
	// than guessing. Null until it loads — the template shows a skeleton meanwhile.
	return pendingItems.value.find((r) => r.name === route.query.e)?._type || null
})

const search = ref("")
const inItems = ref([])
const outItems = ref([])

// Pending EIR-In (auto-created per container when an Order Bongkar is submitted).
const inRes = cachedResource({
	url: "container_depot.ess.inspections.eir_pending",
	method: "GET",
	makeParams: () => ({ search: search.value || undefined, page_length: 50 }),
	auto: true,
	onSuccess: (data) => (inItems.value = (data.items || []).map((x) => ({ ...x, _type: "EIR-In" }))),
})
// Pending EIR-Out (auto-created per container when an Order Muat is submitted).
const outRes = cachedResource({
	url: "container_depot.ess.inspections.eir_out_pending",
	method: "GET",
	makeParams: () => ({ search: search.value || undefined, page_length: 50 }),
	auto: true,
	onSuccess: (data) => (outItems.value = (data.items || []).map((x) => ({ ...x, _type: "EIR-Out" }))),
})

// How tall the batch navigator is, published for whatever floats beneath it (the EIR form
// header). Zero — not "unset" — while there is no navigator, so the form header comes back
// up flush against the app bar the moment the batch is left.
const navBar = ref(null)
let navWatcher = null
function setNavHeight(px) {
	document.documentElement.style.setProperty("--oak-nav-h", `${px}px`)
}
watch(
	navBar,
	(el) => {
		navWatcher?.disconnect()
		navWatcher = null
		if (!el || typeof ResizeObserver === "undefined") {
			setNavHeight(0)
			return
		}
		navWatcher = new ResizeObserver(([entry]) => {
			const h = entry.borderBoxSize?.[0]?.blockSize ?? entry.target.getBoundingClientRect().height
			setNavHeight(Math.round(h))
		})
		navWatcher.observe(el)
	},
	{ flush: "post" },
)
onBeforeUnmount(() => {
	navWatcher?.disconnect()
	setNavHeight(0)
})

// --- queue navigator + batch selection --------------------------------------
// "Pilih" (select mode) lets the surveyor tick several pending EIRs, then "Buka" opens
// them as a batch. The navigator walks that picked set — no need to press Mulai and no
// need to submit to move on; every edit already auto-saves. The batch persists (as names)
// until it's cleared or every EIR in it leaves the pending list.
const selectMode = ref(false)
const selected = reactive(new Set())
const autoAdvanceTo = ref(null) // next EIR to open after a submit (consumed by onBack)

// Persist the batch so a page refresh on an open EIR keeps the navigator (the ?e= URL alone
// only restores the single open EIR). sessionStorage = scoped to this tab/session.
const BATCH_KEY = "eir_batch"
try {
	const saved = JSON.parse(sessionStorage.getItem(BATCH_KEY) || "[]")
	if (Array.isArray(saved)) saved.forEach((n) => selected.add(n))
} catch {
	/* ignore malformed storage */
}
watch(
	() => Array.from(selected),
	(arr) => sessionStorage.setItem(BATCH_KEY, JSON.stringify(arr))
)

// The batch = the picked EIRs that are still pending, in worklist order.
const navQueue = computed(() => pendingItems.value.filter((r) => selected.has(r.name)))
const activeIndex = computed(() => navQueue.value.findIndex((r) => r.name === activeInspection.value))
const activeItem = computed(() => navQueue.value[activeIndex.value] || null)

const loadingPending = computed(() => inRes.loading || outRes.loading)
const fetchError = computed(() => {
	const e = inRes.error || outRes.error
	return e ? e.messages?.[0] || e.message : null
})

// Merge both queues, in the same three tiers the server sorts every worklist by
// (container_depot.container_depot.worklist): the customer's lift-on date first, then the
// inspection already in this surveyor's hands, then the rest newest-first.
//
// Re-sorted here at all only because this screen is the one that MERGES two server lists —
// EIR-In and EIR-Out arrive separately, each already ordered, and concatenating them would
// otherwise put every outbound tank below every inbound one. Sorting by anything other than
// the server's own rule is what used to happen here, and it quietly dropped gate-out
// priority off the one screen that most needed it.
const pendingItems = computed(() => {
	// An EIR whose submit is queued has left this queue, whatever the server still says. The
	// list is only refreshed when there is a link, so without this the surveyor sees the tank
	// they just finished sitting there untouched and inspects it again.
	const all = [...inItems.value, ...outItems.value]
	const NO_DATE = "9999-12-31" // sorts after every real date, same as the server's sentinel
	// Tanggal survey dulu, baru rencana pickup — cermin `worklist.priority_date`. Kalau
	// keduanya berselisih, layar ini yang salah: server yang memutuskan urutan.
	const due = (r) => String(r.target_survey_on || r.target_lift_on || NO_DATE)
	all.sort((a, b) => {
		const lift = due(a).localeCompare(due(b))
		if (lift) return lift
		const started = Number(!!b.work_started_on) - Number(!!a.work_started_on)
		return started || String(b.creation || "").localeCompare(String(a.creation || ""))
	})
	return all
})

// Worklist filters, two independent dimensions: how far along an EIR is (Belum /
// Dikerjakan) and which direction it is (Masuk / Keluar). "Selesai" is not a choice on
// either: a submitted EIR leaves the pending queue entirely and shows in its own section
// below.
const filter = ref("all")
const dirFilter = ref("all")
const byStatus = (list) =>
	filter.value === "started"
		? list.filter((r) => r.work_started_on)
		: filter.value === "todo"
			? list.filter((r) => !r.work_started_on)
			: list
const byDir = (list) =>
	dirFilter.value === "all" ? list : list.filter((r) => r._type === dirFilter.value)

// Each row counts the list the OTHER row has already narrowed, so the numbers always add
// up to what tapping that button would actually show.
const dirScoped = computed(() => byDir(pendingItems.value))
const statusScoped = computed(() => byStatus(pendingItems.value))
const visibleItems = computed(() => byStatus(dirScoped.value))
const FILTERS = computed(() => {
	const list = dirScoped.value
	return [
		{ key: "all", label: labels.eirFilterAll, count: list.length },
		{ key: "todo", label: labels.eirFilterNotStarted, count: list.filter((r) => !r.work_started_on).length },
		{ key: "started", label: labels.eirFilterStarted, count: list.filter((r) => r.work_started_on).length },
	]
})
const DIR_FILTERS = computed(() => {
	const list = statusScoped.value
	return [
		{ key: "all", label: labels.eirFilterAll, count: list.length },
		{ key: "EIR-In", label: labels.eirBadgeIn, count: list.filter((r) => r._type === "EIR-In").length },
		{ key: "EIR-Out", label: labels.eirBadgeOut, count: list.filter((r) => r._type === "EIR-Out").length },
	]
})
const emptyText = computed(() => {
	if (!pendingItems.value.length) return labels.eirPendingEmpty
	if (dirFilter.value === "EIR-In" && !dirScoped.value.length) return labels.eirFilterEmptyIn
	if (dirFilter.value === "EIR-Out" && !dirScoped.value.length) return labels.eirFilterEmptyOut
	if (filter.value === "started") return labels.eirFilterEmptyStarted
	if (filter.value === "todo") return labels.eirFilterEmptyNotStarted
	return labels.eirPendingEmpty
})

let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(reloadPending, 300)
}
function reloadPending() {
	inRes.reload()
	outRes.reload()
}


// Landing "recently submitted" — the caller's own latest completed EIRs (In & Out),
// newest first (no date filter). Tapping one opens its read-only detail (+ revision).
const LANDING_LIMIT = 5
const doneItems = ref([])
const doneRes = cachedResource({
	url: "container_depot.ess.inspections.eir_history",
	method: "GET",
	makeParams: () => ({ docstatus: 1, page_length: LANDING_LIMIT }),
	auto: true,
	onSuccess: (data) => (doneItems.value = data.items || []),
})

// "Diajukan Review" — the caller's own EIRs sent for review (Pending Review, still
// docstatus 0), awaiting Admin Ops's Desk Submit. Read-only, opened like a completed one.
const reviewItems = ref([])
const reviewRes = cachedResource({
	url: "container_depot.ess.inspections.eir_pending_review",
	method: "GET",
	makeParams: () => ({ page_length: 20 }),
	auto: true,
	onSuccess: (data) => (reviewItems.value = data.items || []),
})

function goItem(r) {
	router.push({ query: { e: r.name, t: r._type === "EIR-Out" ? "out" : "in" } })
}
// Completed EIRs are read-only: open the History detail (which carries the revision button).
function goCompleted(r) {
	router.push({ path: "/eir/history", query: { open: r.name } })
}
// Prev/next within the picked batch — keep the scroll position so moving between EIRs lands
// on the SAME section (e.g. the photos) instead of jumping back to the top. The next form
// re-mounts (collapsing height), so we re-apply the saved offset over a few frames until the
// page is tall enough to reach it again.
function goRel(delta) {
	const len = navQueue.value.length
	if (len < 2) return
	// Wrap around: Next on the last EIR loops back to the first (and Prev on the first to
	// the last), so you can keep cycling the batch without hitting a dead end.
	const target = navQueue.value[(activeIndex.value + delta + len) % len]
	if (!target) return
	keepScrollForNextNavigation()
	restoreScrollTo(window.scrollY)
	goItem(target)
}
function restoreScrollTo(y) {
	if (y <= 0) return
	let tries = 0
	const tick = () => {
		const maxY = document.documentElement.scrollHeight - window.innerHeight
		if (maxY >= y - 2 || tries >= 90) {
			window.scrollTo(0, Math.min(y, Math.max(0, maxY)))
			// One late re-apply catches images/thumbnails that settle after first paint.
			if (tries < 90) setTimeout(() => window.scrollTo(0, Math.min(y, Math.max(0, document.documentElement.scrollHeight - window.innerHeight))), 250)
			return
		}
		tries++
		requestAnimationFrame(tick)
	}
	requestAnimationFrame(tick)
}

// Worklist tap: select in batch mode, otherwise open the EIR.
function rowClick(r) {
	if (selectMode.value) {
		if (selected.has(r.name)) selected.delete(r.name)
		else selected.add(r.name)
		return
	}
	goItem(r)
}
function toggleSelectMode() {
	selectMode.value = !selectMode.value
	selected.clear()
}

// Open the picked EIRs as a batch: just navigate to the first — no Mulai, no submit. The
// selection stays as the batch so the ◀ / ▶ navigator can walk it. Each EIR still has its
// own Mulai gate for editing; moving between them needs neither Mulai nor submit.
function openBatch() {
	const first = pendingItems.value.find((r) => selected.has(r.name)) // worklist order
	if (!first) return
	selectMode.value = false // keep `selected` — it IS the batch now
	goItem(first)
}
// Leave the batch (clears the picked set) and drop back to the worklist.
function clearBatch() {
	selected.clear()
	if (route.query.e) router.push({ query: {} })
}

function onBack() {
	// After a submit the child emits `submitted` (which queued the next EIR) then `back`.
	const next = autoAdvanceTo.value
	autoAdvanceTo.value = null
	if (next) {
		goItem(next) // auto-advance to the next EIR in this account's queue
		reloadPending()
		doneRes.reload()
		reviewRes.reload()
		return
	}
	if (route.query.e) router.push({ query: {} })
	reloadPending()
	doneRes.reload()
	reviewRes.reload()
}
function onSubmitted(name) {
	// Capture the next EIR to jump to BEFORE the lists refresh (the just-submitted one is
	// still in navQueue here). Prefer the following item, else the previous, else stop.
	const q = navQueue.value
	const i = q.findIndex((r) => r.name === name)
	const next = i === -1 ? null : q[i + 1] || q[i - 1] || null
	autoAdvanceTo.value = next && next.name !== name ? next : null
	selected.delete(name) // the submitted EIR leaves the batch
}
</script>
