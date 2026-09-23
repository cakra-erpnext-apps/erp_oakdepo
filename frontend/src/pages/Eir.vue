<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- =================== FORM (In or Out) =================== -->
		<template v-if="activeInspection && activeType">
			<!-- Bar batch: hanya muncul kalau memang ada lebih dari satu EIR yang dibuka
			     bersama. Ia yang mengumumkan --oak-nav-h, jadi header form di bawahnya
			     otomatis turun satu bar (lihat EirBatchBar.vue). -->
			<EirBatchBar
				v-if="batchRows.length > 1 && activeIndex !== -1"
				:queue="batchRows"
				:active-index="activeIndex"
				:tanks="activeTanks"
				@prev="goRel(-1)"
				@next="goRel(1)"
				@open="sheetOpen = true"
			/>
			<component
				:is="activeType === 'EIR-Out' ? EirOutForm : EirInForm"
				:key="activeInspection + activeType"
				:inspection="activeInspection"
				@back="onBack"
				@submitted="onSubmitted"
			/>
			<EirBatchSheet
				:open="sheetOpen"
				:rows="batchRows"
				:active-name="activeInspection || ''"
				:tanks="activeTanks"
				@close="sheetOpen = false"
				@leave="clearBatch"
				@pick="goItem"
			/>
		</template>
		<!-- ?e= without ?t= (hand-typed / shared link): the worklist is still resolving
		     which direction this EIR is. Rendering the wrong form would call the wrong
		     endpoint, so wait rather than guess. -->
		<div v-else-if="activeInspection" class="oak-section space-y-2">
			<div class="oak-skeleton h-6 w-1/2 rounded-md"></div>
			<div class="oak-skeleton h-24 rounded-xl"></div>
		</div>

		<!-- =================== BATCH SELESAI =================== -->
		<!-- Bon yang seluruh tanknya sudah dikirim. Bukan sekadar toast: sebuah batch adalah
		     satu truk yang selesai dilayani, dan operator berhak melihat ringkasannya sekali
		     — apa yang terkirim, berapa temuannya, berapa lama — sebelum daftar kembali
		     penuh dengan pekerjaan berikutnya. -->
		<template v-else-if="batchDone">
			<section class="space-y-4 py-6 text-center">
				<span class="oak-icon-tile mx-auto h-16 w-16 rounded-full bg-leaf-100 text-leaf-600">
					<Icon name="check" :size="32" />
				</span>
				<div>
					<h1 class="text-lg font-extrabold tracking-tight">
						{{ labels.eirBatchDoneTitle }} · {{ sentSummary.length }} {{ labels.eirBatchDoneSent }}
					</h1>
					<p v-if="batch.voucher" class="mt-0.5 font-mono text-xs text-gray-500">{{ batch.voucher }}</p>
				</div>

				<ul class="oak-card divide-y divide-gray-100 overflow-hidden text-left">
					<li v-for="r in sentSummary" :key="r.name" class="flex items-center gap-3 px-4 py-3">
						<span class="oak-icon-tile h-7 w-7 bg-leaf-100 text-leaf-700"><Icon name="check" :size="15" /></span>
						<span class="min-w-0 flex-1">
							<span class="block truncate font-mono text-sm font-bold text-gray-900">{{ r.container_no }}</span>
							<span class="block truncate text-[11px] text-gray-500">{{ doneLine(r) }}</span>
						</span>
						<span class="oak-chip shrink-0 bg-sky-100 text-sky-700">{{ labels.eirStatusPendingReview }}</span>
					</li>
				</ul>

				<p class="px-2 text-xs text-gray-400">{{ labels.eirBatchDoneNote }}</p>
			</section>

			<div class="oak-footer -mx-4 space-y-2 border-t border-gray-200/80 bg-gray-50/95 px-4 py-3 backdrop-blur">
				<button class="oak-btn oak-btn-primary w-full py-3" @click="finishBatch(false)">
					{{ labels.eirBatchDoneBack }}
				</button>
				<button class="oak-btn oak-btn-secondary w-full py-2.5" @click="finishBatch(true)">
					{{ labels.eirBatchDoneNew }}
				</button>
			</div>
		</template>

		<!-- =================== DAFTAR =================== -->
		<!-- Tata letak = Jadwal Survey (SurveyOrderList): cari, pil status, filter + urut, grup
		     per tanggal target. Yang sedang dikerjakan jadi kartu besar; sisanya baris ringkas.
		     EIR yang sudah selesai tinggal di Riwayat. -->
		<template v-else>
			<div class="flex items-start justify-between gap-3">
				<div class="min-w-0">
					<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.eirTitle }}</h1>
					<p class="mt-0.5 truncate text-xs text-gray-500">{{ labels.eirCombinedSubtitle }}</p>
				</div>
				<!-- Sedang memilih batch: satu-satunya jalan keluar berada di tempat yang sama
				     dengan pintu masuknya. Sortir & Riwayat menepi — keduanya pindah layar, dan
				     pilihan yang sedang disusun ikut hilang. -->
				<button
					v-if="selectMode"
					class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 border-brand-300 px-3 text-brand-700"
					@click="toggleSelectMode"
				>
					<Icon name="x" :size="15" /> {{ labels.eirSelectCancel }}
				</button>
				<div v-else class="flex shrink-0 items-center gap-2">
					<button class="oak-btn oak-btn-secondary min-h-[44px] px-3" @click="toggleSelectMode">
						<Icon name="check-square" :size="15" /> {{ labels.eirSelect }}
					</button>
					<router-link to="/eir/sort" class="oak-btn oak-btn-secondary min-h-[44px] px-3" :aria-label="labels.eirSortOpen">
						<Icon name="layers" :size="15" />
					</router-link>
					<router-link to="/eir/history" class="oak-btn oak-btn-secondary min-h-[44px] px-3">
						<Icon name="clock" :size="15" /> {{ labels.navHistory }}
					</router-link>
				</div>
			</div>

			<!-- Batch yang sedang terbuka — pintu pulang ke batch setelah Kembali dari form.
			     Yang dipajang nomor tank-nya, bukan nomor bon: itulah yang tertulis di tangki. -->
			<div
				v-if="openBatchRows.length > 1 && !selectMode"
				class="flex items-center gap-3 rounded-xl border border-brand-200 bg-brand-50 p-3"
			>
				<span class="oak-icon-tile h-9 w-9 shrink-0 bg-brand-100 text-brand-700">
					<Icon name="layers" :size="18" />
				</span>
				<div class="min-w-0 flex-1">
					<p class="truncate text-sm font-bold text-gray-900">
						{{ labels.eirBatchTitle }} · <span class="font-mono">{{ openBatchTanks }}</span>
					</p>
					<p class="truncate text-[11px] text-gray-500">{{ openBatchLine }}</p>
				</div>
				<button class="oak-btn oak-btn-ghost shrink-0 px-2 py-2 text-xs" @click="clearBatch">
					{{ labels.eirBatchExit }}
				</button>
				<button v-if="resumeRow" class="oak-btn oak-btn-primary shrink-0 px-3 py-2 text-xs" @click="goItem(resumeRow)">
					{{ labels.eirBatchResume }}
				</button>
			</div>

			<ListSearch v-model="search" :placeholder="labels.eirListSearch" @search="reload" />

			<StatPills :pills="pills" :model-value="f.status" @update:model-value="setStatus" />

			<FilterBar
				:chips="activeChips"
				:sort-label="f.sort === 'newest' ? labels.svSortNewest : labels.listSortPriority"
				:show-clear="!!search"
				@open="filterOpen = true"
				@sort="toggleSort"
				@clear-one="clearOne"
				@clear-all="clearAll"
			/>

			<FilterSheet
				:open="filterOpen"
				:value="f"
				:options="options"
				:fields="SHEET_FIELDS"
				@close="filterOpen = false"
				@apply="applyFilter"
			/>

			<!-- Satu bon, beberapa tank: data rujukan sama untuk semuanya — janji "diisi sekali"
			     hanya boleh muncul kalau yang dicentang memang satu bon. -->
			<div
				v-if="selectMode && selected.size > 1 && sharedVoucher"
				class="flex items-start gap-2 rounded-xl border border-blue-200 bg-blue-50 p-3 text-blue-800"
			>
				<Icon name="info" :size="16" class="mt-0.5 shrink-0" />
				<div class="min-w-0 text-[11px] leading-snug">
					<p class="font-bold">{{ labels.eirBatchVoucherTitle.replace("{n}", selected.size) }}</p>
					<p class="truncate opacity-80">
						<span class="font-mono">{{ sharedVoucher }}</span> · {{ labels.eirBatchVoucherHint }}
					</p>
				</div>
			</div>

			<SkeletonList v-if="listRes.loading && !items.length" :action="false" />

			<div v-else-if="failed" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
				<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
				<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
				<button class="oak-btn oak-btn-primary mt-1 min-h-[44px] px-4" @click="reload">{{ labels.monitorRetry }}</button>
			</div>

			<div v-else-if="!items.length" class="oak-card flex flex-col items-center gap-1 p-8 text-center">
				<span class="oak-icon-tile h-11 w-11 bg-gray-100 text-gray-300"><Icon name="inbox" :size="22" /></span>
				<p class="text-sm font-semibold text-gray-500">{{ labels.eirListEmpty }}</p>
				<!-- Kalimat kedua hanya untuk kosong yang sebenar-benarnya, bukan kosong karena saringan. -->
				<p v-if="!counts.all" class="text-xs text-gray-400">{{ labels.eirPendingEmptyHint }}</p>
			</div>

			<div v-else class="space-y-4">
				<section v-for="g in days" :key="g.date" class="space-y-2">
					<div class="flex items-center justify-between gap-2 px-1">
						<p class="flex min-w-0 items-center gap-1.5 truncate text-xs font-bold" :class="g.hot ? 'text-red-600' : 'text-gray-600'">
							<span class="h-2 w-2 shrink-0 rounded-full" :class="g.hot ? 'bg-red-500' : 'bg-gray-400'"></span>
							{{ g.label }}
						</p>
						<button
							v-if="selectMode && g.rows.some(selectable)"
							class="oak-press shrink-0 text-[11px] font-bold text-brand-600"
							@click="selectAll(g.rows.filter(selectable))"
						>
							{{ labels.eirBatchSelectAll }}
						</button>
						<p v-else class="shrink-0 text-[11px] text-gray-400">{{ fill(labels.eirCount, { n: dayCounts[g.date] || g.rows.length }) }}</p>
					</div>

					<!-- Dikerjakan: kartu besar dengan tombol lanjut. -->
					<button
						v-for="o in g.running"
						:key="o.name"
						type="button"
						class="oak-card oak-press block w-full space-y-2.5 p-4 text-left"
						:class="selected.has(o.name) ? 'ring-2 ring-brand-500' : ''"
						@click="open(o)"
					>
						<span class="flex items-start gap-2">
							<span
								v-if="selectMode"
								class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border"
								:class="selected.has(o.name) ? 'border-brand-500 bg-brand-500 text-white' : 'border-gray-300'"
							>
								<Icon v-if="selected.has(o.name)" name="check" :size="14" />
							</span>
							<EirInfo :o="o" class="flex-1">
								<span class="oak-chip shrink-0" :class="stateChip(o).tone">{{ stateChip(o).label }}</span>
							</EirInfo>
						</span>
						<span class="flex flex-wrap items-center gap-1.5 text-[11px]">
							<span class="oak-chip shrink-0" :class="dirChip(o).tone">
								<Icon :name="dirChip(o).icon" :size="11" /> {{ dirChip(o).label }}
							</span>
							<span v-if="bonSize(o) > 1" class="oak-chip shrink-0 bg-brand-100 text-brand-700">
								<Icon name="layers" :size="11" /> {{ labels.eirBatchTitle }} {{ bonSize(o) }}
							</span>
							<LiftOnBadge :survey="o.target_survey_on" :target="o.target_lift_on" :urgent="o.target_urgent_on" />
						</span>
						<span v-if="o.started_by_name" class="flex items-center gap-1.5 text-xs">
							<Icon name="user" :size="13" class="shrink-0 text-gray-400" />
							<span class="text-gray-400">{{ labels.svWorkedBy }}</span>
							<span class="min-w-0 truncate font-semibold text-gray-700">{{ o.started_by_name }}</span>
						</span>
						<!-- Langkah hanya untuk EIR yang pernah dibuka di HP ini — "1/4" untuk tank
						     yang dimulai rekan kemarin adalah tebakan. -->
						<span v-if="hasStep(o.name)" class="block h-1.5 overflow-hidden rounded-full bg-gray-100">
							<span class="block h-full rounded-full bg-brand-500" :style="{ width: `${((getStep(o.name) + 1) / STEP_COUNT) * 100}%` }"></span>
						</span>
						<span v-if="!selectMode" class="oak-btn oak-btn-primary min-h-[48px] w-full">
							<Icon name="play-circle" :size="16" /> {{ labels.eirResume }}
						</span>
					</button>

					<!-- Sisanya: baris ringkas. -->
					<ul v-if="g.rest.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
						<li v-for="o in g.rest" :key="o.name">
							<button
								type="button"
								class="oak-press flex min-h-[64px] w-full items-center gap-2 px-4 py-3 text-left"
								:class="selectMode && !selectable(o) ? 'opacity-50' : ''"
								@click="open(o)"
							>
								<span
									v-if="selectMode && selectable(o)"
									class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border"
									:class="selected.has(o.name) ? 'border-brand-500 bg-brand-500 text-white' : 'border-gray-300'"
								>
									<Icon v-if="selected.has(o.name)" name="check" :size="14" />
								</span>
								<span class="min-w-0 flex-1">
									<EirInfo :o="o">
										<span class="oak-chip shrink-0" :class="stateChip(o).tone">{{ stateChip(o).label }}</span>
									</EirInfo>
									<span class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
										<span class="oak-chip shrink-0" :class="dirChip(o).tone">
											<Icon :name="dirChip(o).icon" :size="11" /> {{ dirChip(o).label }}
										</span>
										<span v-if="selectable(o) && bonSize(o) > 1" class="oak-chip shrink-0 bg-brand-100 text-brand-700">
											<Icon name="layers" :size="11" /> {{ labels.eirBatchTitle }} {{ bonSize(o) }}
										</span>
										<LiftOnBadge :survey="o.target_survey_on" :target="o.target_lift_on" :urgent="o.target_urgent_on" />
									</span>
									<!-- Review: sudah berapa lama menunggu, dan pada siapa. -->
									<span
										v-if="o.state === 'review' && (o.inspector_name || o.modified)"
										class="mt-1 flex items-center gap-1 truncate text-[11px] text-gray-400"
									>
										<Icon name="clock" :size="11" class="shrink-0" />
										{{ [since(o.modified), o.inspector_name].filter(Boolean).join(" · ") }}
									</span>
								</span>
								<Icon v-if="!selectMode" name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
							</button>
						</li>
					</ul>
				</section>

				<button
					v-if="items.length < total"
					class="oak-btn oak-btn-secondary min-h-[48px] w-full"
					:disabled="listRes.loading"
					@click="loadMore"
				>
					{{ listRes.loading ? "…" : `${labels.svMore} (${items.length}/${total})` }}
				</button>
			</div>

			<!-- Aksi utama mode pilih, menempel di bawah: daftar bisa panjang. -->
			<div
				v-if="selectMode && selected.size"
				class="oak-footer -mx-4 border-t border-gray-200/80 bg-gray-50/95 px-4 py-3 backdrop-blur"
			>
				<button class="oak-btn oak-btn-primary w-full py-3" @click="openBatchNow">
					{{ labels.eirBatchOpenBtn }} · {{ selected.size }} {{ labels.eirBadge }}
				</button>
				<p class="mt-1.5 text-center text-[11px] text-gray-400">{{ labels.eirBatchOpenHint }}</p>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { fmtDate, since } from "@/utils/surveyStatus"
import Icon from "@/components/Icon.vue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import EirBatchBar from "@/components/EirBatchBar.vue"
import EirBatchSheet from "@/components/EirBatchSheet.vue"
import EirInfo from "@/components/EirInfo.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import StatPills from "@/components/list/StatPills.vue"
import FilterBar from "@/components/list/FilterBar.vue"
import FilterSheet from "@/components/list/FilterSheet.vue"
import { daysFrom, fill, groupByDay, useSavedFilters } from "@/utils/listKit"
import { cachedResource } from "@/data/cache"
import { keepScrollForNextNavigation } from "@/router"
import EirInForm from "@/pages/EirInForm.vue"
import EirOutForm from "@/pages/EirOutForm.vue"
import {
	STEP_COUNT,
	batch,
	getStep,
	hasPending,
	hasStep,
	leaveBatch,
	openBatch,
	sentRows,
	tankNo,
} from "@/utils/eirBatch"


const route = useRoute()
const router = useRouter()

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

// Pending EIR-In / EIR-Out (auto-created per bon) — the batch backbone: bon mates, batch rows
// and the ?e= direction are read from these full, UNfiltered lists, so a search or filter on the
// list below never splits a batch. The screen itself draws `eir_list`.
// Pending EIR-In (auto-created per container when an Order Bongkar is submitted).
const inRes = cachedResource({
	url: "container_depot.ess.inspections.eir_pending",
	method: "GET",
	makeParams: () => ({ page_length: 50 }),
	auto: true,
	onSuccess: (data) => (inItems.value = (data.items || []).map((x) => ({ ...x, _type: "EIR-In" }))),
})
// Pending EIR-Out (auto-created per container when an Order Muat is submitted).
const outRes = cachedResource({
	url: "container_depot.ess.inspections.eir_out_pending",
	method: "GET",
	makeParams: () => ({ page_length: 50 }),
	auto: true,
	onSuccess: (data) => (outItems.value = (data.items || []).map((x) => ({ ...x, _type: "EIR-Out" }))),
})

// --- batch: memilih, membuka, berpindah ---------------------------------------
// "Pilih" mencentang beberapa EIR pending; "Buka batch" menyerahkannya ke utils/eirBatch,
// yang memegang urutan, langkah, papan salin, dan catatan kiriman sampai batch ditutup.
// Tidak perlu Mulai dan tidak perlu submit untuk berpindah antar anggotanya — setiap
// perubahan sudah tersimpan otomatis.
const selectMode = ref(false)
const selected = reactive(new Set())
const sheetOpen = ref(false)
const batchDone = ref(false)
const autoAdvanceTo = ref(null) // EIR berikutnya yang dibuka setelah sebuah submit

// Anggota batch dengan barisnya masing-masing. Yang sudah dikirim tidak ada lagi di
// worklist, jadi barisnya dirakit dari catatan kiriman — bar dan sheet tetap harus bisa
// menunjukkan tank itu ada dan sudah beres.
const batchRows = computed(() =>
	batch.names
		.map((n) => {
			const sent = batch.sent[n]
			const row = pendingItems.value.find((r) => r.name === n)
			if (row) return { ...row, sent }
			return sent ? { name: n, container_no: sent.container_no || tankNo(n), sent } : null
		})
		.filter(Boolean)
)
const activeIndex = computed(() => batchRows.value.findIndex((r) => r.name === activeInspection.value))
// Batch yang masih terbuka saat operator berdiri di daftar — bahan banner "lanjutkan".
const openBatchRows = computed(() =>
	activeInspection.value || batchDone.value || !hasPending() ? [] : batchRows.value
)
const resumeRow = computed(() => openBatchRows.value.find((r) => !r.sent && r._type) || null)
// Isi batch dalam bahasa yang dipakai di lapangan: nomor tank, bukan nomor dokumen.
const openBatchTanks = computed(() => tanksOf(openBatchRows.value))
const activeTanks = computed(() => tanksOf(batchRows.value))
function tanksOf(rows) {
	return rows.map((r) => r.container_no || r.container || tankNo(r.name)).filter(Boolean).join(", ")
}

const openBatchLine = computed(() => {
	const rows = openBatchRows.value
	const sent = rows.filter((r) => r.sent).length
	const parts = [`${rows.length} ${labels.eirBadge}`]
	if (sent) parts.push(`${sent} ${labels.eirBatchSentWord.toLowerCase()}`)
	parts.push(`${rows.length - sent} ${labels.eirBatchTodoWord.toLowerCase()}`)
	return parts.join(" · ")
})
const sentSummary = computed(() => sentRows())

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
	const all = [...inItems.value, ...outItems.value]
	const NO_DATE = "9999-12-31" // sorts after every real date, same as the server's sentinel
	// Tanggal survey dulu, baru rencana pickup — cermin `worklist.priority_date`. Kalau
	// keduanya berselisih, layar ini yang salah: server yang memutuskan urutan.
	const due = (r) => String(r.target_survey_on || r.target_lift_on || NO_DATE)
	// ...dan di atas keduanya tanda mendesak — tier 0 di `worklist.sort_by_priority`, diurut
	// memakai tanggal mendesaknya sendiri persis seperti server.
	const urgent = (r) => (r.target_urgent_on ? String(r.target_urgent_on) : "")
	all.sort((a, b) => {
		const flag = Number(!urgent(a)) - Number(!urgent(b))
		if (flag) return flag
		if (urgent(a) && urgent(b)) {
			const u = urgent(a).localeCompare(urgent(b))
			if (u) return u
		}
		const lift = due(a).localeCompare(due(b))
		if (lift) return lift
		const started = Number(!!b.work_started_on) - Number(!!a.work_started_on)
		return started || String(b.creation || "").localeCompare(String(a.creation || ""))
	})
	return all
})

// Sejauh mana satu EIR sudah dikerjakan. Langkahnya hanya dicetak untuk EIR yang memang
// pernah dibuka di sesi ini — "Draft 1/4" untuk tank yang dimulai rekan kemarin adalah
// tebakan, dan tebakan di worklist dibaca sebagai fakta.
function progressChip(r) {
	if (!r.work_started_on) return { label: labels.eirBatchNotStarted, tone: "bg-gray-100 text-gray-500" }
	if (hasStep(r.name))
		return {
			label: `${labels.eirDraftStep} ${getStep(r.name) + 1}/${STEP_COUNT}`,
			tone: "bg-brand-100 text-brand-700",
		}
	return { label: labels.eirChipStarted, tone: "bg-amber-100 text-amber-800" }
}

// Bon yang sama untuk semua yang dicentang — atau kosong kalau campur.
const sharedVoucher = computed(() => {
	const vouchers = new Set(
		pendingItems.value.filter((r) => selected.has(r.name)).map((r) => r.referred_voucher || "")
	)
	return vouchers.size === 1 ? [...vouchers][0] : ""
})

function reloadLists() {
	inRes.reload()
	outRes.reload()
	reload()
}

// --- daftar (eir_list): cari, pil status, filter, urut, grup per tanggal --------------------
// Filter disimpan per user di perangkat ini (utils/listKit); pencarian tidak.
const PAGE = 20
const SHEET_DEFAULTS = { type: "", day: "", depot: "", principal: "" }
const TYPE_LABEL = { "EIR-In": labels.eirBadgeIn, "EIR-Out": labels.eirBadgeOut }
const SHEET_FIELDS = [
	{
		key: "type", type: "scope",
		choices: [{ key: "", label: labels.eirFilterAll }, { key: "EIR-In", label: labels.eirBadgeIn }, { key: "EIR-Out", label: labels.eirBadgeOut }],
	},
	{ key: "day", type: "date", label: labels.svChipDate },
	{ key: "depot", type: "chips", list: "depots", label: labels.svChipDepot },
	{ key: "principal", type: "select", list: "principals", label: labels.svChipPrincipal },
]
const f = useSavedFilters("eir", { ...SHEET_DEFAULTS, status: "", sort: "priority" })
if (f.sort !== "newest") f.sort = "priority"
// ?s=doing|todo|review — kartu Beranda mendarat di pil yang angkanya barusan ditekan.
// "done" (EIR selesai) kini tinggal di Riwayat.
if (["todo", "doing", "review"].includes(route.query.s)) f.status = route.query.s
else if (route.query.s === "done") router.replace("/eir/history")
const filterOpen = ref(false)

const activeChips = computed(() =>
	[
		f.type && { key: "type", label: labels.eirTypeFilter, value: TYPE_LABEL[f.type] || f.type },
		f.day && { key: "day", label: labels.svChipDate, value: fmtDate(f.day) },
		f.depot && { key: "depot", label: labels.svChipDepot, value: f.depot },
		f.principal && { key: "principal", label: labels.svChipPrincipal, value: f.principal },
	].filter(Boolean)
)
function clearOne(key) {
	f[key] = SHEET_DEFAULTS[key]
	reload()
}
function applyFilter(draft) {
	Object.assign(f, draft)
	reload()
}
function clearAll() {
	search.value = ""
	Object.assign(f, SHEET_DEFAULTS, { status: "", sort: "priority" })
	reload()
}

const items = ref([])
const total = ref(0)
const counts = ref({})
const options = ref({ depots: [], principals: [] })
const dayCounts = ref({})
const failed = ref(false)
const start = ref(0)

// Angka pil dihitung server TANPA filter — pil adalah cara berpindah filter.
const pills = computed(() => [
	{ key: "", label: labels.svStatAll, count: counts.value.all || 0, tone: "text-gray-900" },
	{ key: "todo", label: labels.listStatTodo, count: counts.value.todo || 0, tone: "text-amber-600" },
	{ key: "doing", label: labels.sectionDoing, count: counts.value.doing || 0, tone: "text-brand-600" },
	{ key: "review", label: labels.listStatReview, count: counts.value.review || 0, tone: "text-sky-600" },
])

// Grup = `group` dari server: tanggal target (Prioritas) atau tanggal EIR dibuat (Terbaru).
// Urutan sepenuhnya dari server (worklist.sort_by_priority).
const days = computed(() =>
	groupByDay(items.value, (o) => o.group, {
		running: (o) => o.state === "doing",
		hot: (o) => o.group === "urgent" || (!!o.due && daysFrom(o.due) <= 0),
	}).map((g) =>
		g.date === "urgent" ? { ...g, label: labels.listUrgentGroup } : g.date ? g : { ...g, label: labels.listNoDueGroup }
	)
)

const listRes = cachedResource({
	url: "container_depot.ess.inspections.eir_list",
	method: "GET",
	makeParams: () => ({
		status: f.status || undefined,
		search: search.value || undefined,
		inspection_type: f.type || undefined,
		day: f.day || undefined,
		depot: f.depot || undefined,
		principal: f.principal || undefined,
		sort: f.sort,
		start: start.value,
		page_length: PAGE,
	}),
	auto: true,
	onSuccess(data) {
		failed.value = false
		const rows = (data?.items || []).map((x) => ({ ...x, _type: x.inspection_type }))
		items.value = start.value ? [...items.value, ...rows] : rows
		total.value = data?.total || 0
		counts.value = data?.counts || {}
		options.value = { depots: data?.depots || [], principals: data?.principals || [] }
		dayCounts.value = data?.day_counts || {}
	},
	onError() {
		failed.value = true
	},
})

function reload() {
	start.value = 0
	listRes.reload()
}
function loadMore() {
	start.value = items.value.length
	listRes.reload()
}
function setStatus(key) {
	f.status = key
	reload()
}
function toggleSort() {
	f.sort = f.sort === "newest" ? "priority" : "newest"
	reload()
}

// Yang sedang review sudah lepas tangan: dibuka baca-saja, tidak ikut batch.
const selectable = (o) => o.state !== "review"
function open(o) {
	if (!selectable(o)) {
		if (!selectMode.value) goCompleted(o)
		return
	}
	rowClick(o)
}
function stateChip(o) {
	if (o.state === "review") return { label: labels.eirStatusPendingReview, tone: "bg-sky-100 text-sky-800" }
	return progressChip(o)
}
function dirChip(o) {
	return o._type === "EIR-Out"
		? { label: labels.eirBadgeOut, icon: "arrow-up-right", tone: "bg-brand-100 text-brand-700" }
		: { label: labels.eirBadgeIn, icon: "arrow-down-left", tone: "bg-leaf-100 text-leaf-800" }
}

function goItem(r) {
	router.push({ query: { e: r.name, t: r._type === "EIR-Out" ? "out" : "in" } })
}
// Completed EIRs are read-only: open the History detail (which carries the revision button).
function goCompleted(r) {
	router.push({ path: "/eir/history", query: { open: r.name } })
}
// Prev/next within the batch — keep the scroll position so moving between EIRs lands
// on the SAME section (e.g. the photos) instead of jumping back to the top. The next form
// re-mounts (collapsing height), so we re-apply the saved offset over a few frames until the
// page is tall enough to reach it again.
function goRel(delta) {
	// Yang sudah dikirim dilewati: ia masih anggota batch (dan masih punya setrip di bar),
	// tapi tidak ada lagi yang bisa dikerjakan di sana.
	const queue = batchRows.value.filter((r) => !r.sent)
	if (queue.length < 2) return
	const i = queue.findIndex((r) => r.name === activeInspection.value)
	// Wrap around: Next on the last EIR loops back to the first (and Prev on the first to
	// the last), so you can keep cycling the batch without hitting a dead end.
	const target = queue[(Math.max(0, i) + delta + queue.length) % queue.length]
	if (!target || target.name === activeInspection.value) return
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

// Tank lain di bon yang sama dan masih harus dikerjakan — termasuk tank ini sendiri.
// Satu bon = satu truk (gate menerbitkannya untuk maksimal dua tank), jadi himpunan
// inilah batch-nya: tidak ada yang perlu dipilih untuk membuatnya ada.
function bonMates(r) {
	if (!r.referred_voucher) return [r]
	return pendingItems.value.filter((x) => x.referred_voucher === r.referred_voucher)
}
// Berapa tank yang dibawa tiap bon — dihitung sekali per daftar, bukan sekali per baris:
// chip "Batch 2" di bawah menanyakannya untuk setiap baris yang digambar.
const bonCount = computed(() => {
	const m = {}
	pendingItems.value.forEach((r) => {
		if (r.referred_voucher) m[r.referred_voucher] = (m[r.referred_voucher] || 0) + 1
	})
	return m
})
function bonSize(r) {
	return (r.referred_voucher && bonCount.value[r.referred_voucher]) || 1
}

// Worklist tap: select in batch mode, otherwise open the EIR.
function rowClick(r) {
	if (selectMode.value) {
		if (selected.has(r.name)) selected.delete(r.name)
		else selected.add(r.name)
		return
	}
	// Menekan anggota batch yang sedang terbuka = melanjutkan batch itu, bukan
	// membubarkannya.
	if (batch.names.includes(r.name)) {
		goItem(r)
		return
	}
	// Tank di luar batch: batch lama ditutup dan bon tank ini yang menggantikannya —
	// otomatis, kalau bonnya memang membawa lebih dari satu tank. Batch tidak lagi harus
	// disusun dengan tangan, dan karena langkah/kiriman tiap EIR tersimpan per EIR (lihat
	// utils/eirBatch), berpindah bolak-balik antar bon tidak menghapus kemajuan mana pun.
	const mates = bonMates(r)
	if (mates.length > 1) {
		openBatch(
			mates.map((m) => ({ name: m.name, container_no: m.container_no || m.container })),
			r.referred_voucher || ""
		)
	} else {
		leaveBatch()
	}
	goItem(r)
}
function toggleSelectMode() {
	selectMode.value = !selectMode.value
	selected.clear()
}
/** "Pilih semua" satu bagian — bukan seluruh halaman: bagian itulah yang sedang dilihat. */
function selectAll(rows) {
	rows.forEach((r) => selected.add(r.name))
}

// Buka EIR yang dicentang sebagai satu batch, urut seperti di worklist, lalu mendarat di
// yang pertama. Tidak ada Mulai dan tidak ada submit di sini: keduanya milik tiap EIR.
function openBatchNow() {
	const members = pendingItems.value.filter((r) => selected.has(r.name))
	if (!members.length) return
	openBatch(
		members.map((r) => ({ name: r.name, container_no: r.container_no || r.container })),
		sharedVoucher.value
	)
	selectMode.value = false
	selected.clear()
	goItem(members[0])
}
// Keluar dari batch (dari sheet) dan kembali ke daftar.
function clearBatch() {
	sheetOpen.value = false
	leaveBatch()
	if (route.query.e) router.push({ query: {} })
}
// Tombol di layar batch selesai: tutup batch, lalu diam di daftar atau langsung memilih
// batch berikutnya (truk berikutnya biasanya sudah menunggu).
function finishBatch(pickAnother) {
	leaveBatch()
	batchDone.value = false
	selectMode.value = pickAnother
	selected.clear()
	reloadLists()
}

function onBack() {
	// After a submit the child emits `submitted` (which queued the next EIR) then `back`.
	const next = autoAdvanceTo.value
	autoAdvanceTo.value = null
	if (next) {
		goItem(next) // lanjut ke anggota batch berikutnya
		reloadLists()
		return
	}
	// Batch yang seluruh anggotanya sudah terkirim berhenti di layar penutupnya, bukan di
	// worklist: itu satu-satunya tempat ringkasan truk tadi masih ada.
	if (batch.names.length && !hasPending()) batchDone.value = true
	if (route.query.e) router.push({ query: {} })
	reloadLists()
}
function onSubmitted(name) {
	// Anggota berikutnya yang belum dikirim — dihitung SEBELUM daftar disegarkan (form sudah
	// mencatat kiriman ini ke batch, jadi ia sendiri sudah tidak masuk hitungan).
	const queue = batchRows.value.filter((r) => !r.sent && r.name !== name)
	autoAdvanceTo.value = queue[0] || null
}

// Nomor batch berganti (batch baru dibuka) — layar penutup yang lama tidak boleh tertinggal.
watch(
	() => batch.names.join(","),
	() => (batchDone.value = false)
)

function doneLine(r) {
	const parts = [
		`${r.damages || 0} ${labels.eirReviewDamage}`,
		`${r.photos || 0} ${labels.eirReviewPhotos}`,
	]
	if (r.minutes) parts.push(`${r.minutes} ${labels.eirMinutes}`)
	return parts.join(" · ")
}
</script>
