<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- =================== DAFTAR + PENCARIAN =================== -->
		<!-- Tata letak = Jadwal Survey (SurveyOrderList): cari, pil, filter + urut, grup per
		     tanggal survey. Satu baris = satu tank di Survey Order booking Tank Out. -->
		<template v-if="!tank">
			<div class="flex items-start justify-between gap-3">
				<div class="min-w-0">
					<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.tankPosTitle }}</h1>
					<p class="mt-0.5 truncate text-xs text-gray-500">{{ labels.tankPosHint }}</p>
				</div>
				<!-- Jalan masuk "dari luar" ke daftar template — untuk yang datang memang untuk
				     merapikan daftarnya, bukan untuk mencatat satu tank. Dari dalam form, panel
				     yang sama muncul sebagai sheet supaya isian tidak dibongkar. -->
				<router-link to="/tank-position/templates" class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-3">
					<Icon name="list" :size="15" /> {{ labels.tplShort }}
				</router-link>
			</div>

			<ListSearch v-model="search" :placeholder="labels.tankPosSearch" @search="onSearch" />

			<!-- Hasil pencarian menggantikan daftar: yang mengetik nomor tank sedang mencari satu
			     tank — di SEMUA tank depo, bukan hanya yang sedang punya job. -->
			<template v-if="search.trim()">
				<ul v-if="searchRows.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
					<PosRow v-for="r in searchRows" :key="r.name" :r="r" />
				</ul>
				<div v-else-if="!searchRes.loading" class="oak-card p-8 text-center text-sm text-gray-400">
					{{ labels.tankPosEmpty }}
				</div>
			</template>

			<template v-else>
				<!-- "Perlu dicek" berdiri sendiri dari "Belum" karena keduanya pekerjaan yang
				     berbeda: yang satu mengisi kekosongan, yang lain memeriksa jawaban yang
				     mungkin sudah bohong. -->
				<StatPills :pills="pills" :model-value="f.group" @update:model-value="setGroup" />

				<FilterBar
					:chips="activeChips"
					:sort-label="f.sort === 'far' ? labels.listSortFar : labels.svSortDue"
					@open="sheetOpen = true"
					@sort="toggleSort"
					@clear-one="clearOne"
					@clear-all="clearAll"
				/>

				<FilterSheet
					:open="sheetOpen"
					:value="f"
					:options="options"
					:fields="SHEET_FIELDS"
					@close="sheetOpen = false"
					@apply="applyFilter"
				/>

				<SkeletonList v-if="boardRes.loading && !items.length" :action="false" />

				<div v-else-if="failed" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
					<span class="oak-icon-tile h-12 w-12 bg-red-50 text-red-500"><Icon name="alert-circle" :size="24" /></span>
					<p class="text-sm font-bold text-gray-900">{{ labels.monitorErrorTitle }}</p>
					<button class="oak-btn oak-btn-primary mt-1 min-h-[44px] px-4" @click="reload">{{ labels.monitorRetry }}</button>
				</div>

				<!-- Tidak ada tank di job. Kalimat keduanya penting: tanpa itu layar kosong
				     terbaca sebagai layar rusak, padahal tank lain tetap bisa dicari. -->
				<div v-else-if="!counts.all" class="oak-card flex flex-col items-center gap-2 p-8 text-center">
					<span class="oak-icon-tile h-12 w-12 bg-leaf-50 text-leaf-500"><Icon name="check-circle" :size="24" /></span>
					<p class="text-sm font-bold text-gray-900">{{ labels.tankPosBoardEmpty }}</p>
					<p class="text-xs text-gray-500">{{ labels.tankPosBoardEmptyHint }}</p>
				</div>

				<p v-else-if="!items.length" class="oak-card p-8 text-center text-sm text-gray-400">{{ labels.tankPosEmpty }}</p>

				<div v-else class="space-y-4">
					<section v-for="g in days" :key="g.date" class="space-y-2">
						<div class="flex items-center justify-between gap-2 px-1">
							<p class="flex min-w-0 items-center gap-1.5 truncate text-xs font-bold" :class="g.hot ? 'text-red-600' : 'text-gray-600'">
								<span class="h-2 w-2 shrink-0 rounded-full" :class="g.hot ? 'bg-red-500' : 'bg-gray-400'"></span>
								{{ g.label }}
							</p>
							<p class="shrink-0 text-[11px] text-gray-400">{{ dayCounts[g.date] || g.rows.length }} {{ labels.bulkTankWord }}</p>
						</div>
						<ul class="oak-card divide-y divide-gray-100 overflow-hidden" :class="g.hot && 'border-red-200'">
							<PosRow v-for="r in g.rows" :key="r.name" :r="r" />
						</ul>
					</section>

					<!-- Catat sekaligus: tank "belum terdata" yang ADA di layar ini. -->
					<button v-if="missingRows.length" class="oak-btn oak-btn-secondary min-h-[48px] w-full" @click="bulkFrom(missingRows)">
						<Icon name="map-pin" :size="15" /> {{ labels.bulkOpen }} · {{ missingRows.length }} {{ labels.bulkTankWord }}
					</button>

					<button
						v-if="items.length < total"
						class="oak-btn oak-btn-secondary min-h-[48px] w-full"
						:disabled="boardRes.loading"
						@click="loadMore"
					>
						{{ boardRes.loading ? "…" : `${labels.svMore} (${items.length}/${total})` }}
					</button>
				</div>
			</template>
		</template>

		<!-- =================== SATU TANK =================== -->
		<template v-else>
			<DetailHeader
				:title="labels.tankPosTitle"
				:chip="tank.located && !tank.fresh ? { label: labels.tankPosStale, cls: 'bg-amber-100 text-amber-800' } : null"
				@back="backToList"
			/>

			<!-- Sudah tersimpan: layar berhenti menjadi form dan menjadi jawaban. -->
			<section v-if="saved" class="oak-card border-leaf-300 p-5 text-center">
				<span class="oak-icon-tile mx-auto h-12 w-12 bg-leaf-500 text-white"><Icon name="check" :size="24" /></span>
				<p class="mt-2 text-base font-extrabold text-gray-900">
					{{ fill(labels.tankPosSavedTitle, { label: saved.location_note }) }}
				</p>
				<p class="mt-0.5 text-xs text-gray-500">
					{{ saved.container }} · {{ fmtDateTime(saved.recorded_on) }}
					<template v-if="saved.recorded_by"> · {{ saved.recorded_by }}</template>
				</p>
				<div class="mt-3 flex gap-2">
					<button class="oak-btn oak-btn-primary min-h-[48px] flex-1" @click="backToList">{{ labels.tankPosNext }}</button>
					<button class="oak-btn oak-btn-secondary min-h-[48px] flex-1" @click="finish">{{ labels.tankPosDone }}</button>
				</div>
			</section>

			<template v-else>
				<SkeletonDetail v-if="pending" :cells="4" :sections="2" />
				<template v-else>
					<!-- Identitas + posisi yang berlaku sekarang -->
					<section class="oak-card space-y-3 p-4">
						<div class="min-w-0">
							<p class="truncate font-mono text-xl font-extrabold tracking-tight text-gray-900">
								{{ tank.container_no || tank.container }}
							</p>
							<p class="truncate text-xs text-gray-500">{{ specLine }}</p>
							<PositionJob v-if="job" :row="job" />
							<router-link
								v-if="job"
								:to="`/survey-orders/order/${encodeURIComponent(job.survey_order)}`"
								class="mt-1 inline-block text-xs font-bold text-brand-600"
							>
								{{ labels.tankPosOpenJob }}
							</router-link>
						</div>
						<div class="grid grid-cols-2 gap-2 border-t border-gray-100 pt-3">
							<div class="min-w-0">
								<p class="text-[11px] text-gray-400">{{ labels.tankPosCurrent }}</p>
								<p class="truncate font-mono text-sm font-bold" :class="tank.located ? 'text-gray-900' : 'text-gray-400'">
									{{ tank.location_note || labels.tankPosUnlocated }}
								</p>
							</div>
							<div class="min-w-0">
								<p class="text-[11px] text-gray-400">{{ labels.tankPosDicatat }}</p>
								<p class="truncate text-sm font-bold text-gray-900">
									{{ tank.located ? since(tank.location_updated_on) : "—" }}
									<template v-if="tank.location_updated_by"> · {{ tank.location_updated_by }}</template>
								</p>
							</div>
						</div>
					</section>

					<!-- Posisi baru -->
					<section class="oak-card space-y-2 border-brand-300 p-4">
						<p class="text-sm font-extrabold text-gray-900">{{ labels.tankPosNewTitle }}</p>
						<PositionTemplateChips v-model="form.location_note" :depot="tank.depot" />
					</section>

					<!-- Foto -->
					<section class="oak-card space-y-2 p-4">
						<div class="flex items-baseline justify-between gap-2">
							<p class="text-sm font-extrabold text-gray-900">{{ labels.tankPosPhotos }}</p>
							<p class="shrink-0 text-[11px] text-gray-400">{{ labels.tankPosOptional }} · {{ labels.tankPosPhotoOne }}</p>
						</div>
						<div class="grid grid-cols-3 items-start gap-2">
							<!-- Keterangan per foto, di bawah petaknya. `location_note` menerangkan
							     SELURUH pembacaan; kotak ini menerangkan satu frame ("di bawah pipa,
							     deret kedua") — dan itulah yang dibaca orang Desk di sebelah fotonya. -->
							<div v-for="(url, i) in form.photos" :key="url" class="space-y-1">
								<div class="relative aspect-square">
									<img
										:src="photoSrc(url)"
										class="h-full w-full rounded-lg border border-gray-200 object-cover"
										@click="openLightbox(form.photos.map((u) => ({ src: photoSrc(u), caption: photoNotes[u] })), i)"
									/>
									<button
										type="button"
										class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white"
										:aria-label="labels.tplCancel"
										@click="removePhoto(i)"
									>
										<Icon name="x" :size="16" />
									</button>
									<PhotoMark :photo="url" />
								</div>
								<input
									v-model="photoNotes[url]"
									type="text"
									class="oak-input px-2 py-1.5 text-xs"
									:placeholder="labels.photoCaption"
								/>
							</div>
							<PhotoTile v-for="it in photoQueue.items" :key="it.id" :item="it" tile="aspect-square w-full" />
							<input ref="camInput" type="file" accept="image/*" capture="environment" multiple class="hidden" @change="onPhotos" />
							<button
								type="button"
								class="flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
								:disabled="photoUploading"
								@click="openCameraOrFallback"
							>
								<Icon v-if="photoUploading" name="loader" :size="22" class="animate-spin" />
								<template v-else>
									<Icon name="camera" :size="22" />
									<span class="text-xs font-medium">{{ labels.photoCamera }}</span>
								</template>
							</button>
							<label class="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100">
								<Icon name="image" :size="22" />
								<span class="text-xs font-medium">{{ labels.photoGallery }}</span>
								<input type="file" accept="image/*" multiple class="hidden" :disabled="photoUploading" @change="onPhotos" />
							</label>
						</div>
						<p class="text-[11px] text-gray-400">{{ labels.tankPosPhotoHint }}</p>
					</section>

					<!-- Catatan -->
					<section class="oak-card space-y-2 p-4">
						<div class="flex items-baseline justify-between gap-2">
							<p class="text-sm font-extrabold text-gray-900">{{ labels.tankPosNote }}</p>
							<p class="shrink-0 text-[11px] text-gray-400">{{ labels.tankPosOptional }}</p>
						</div>
						<textarea v-model.trim="form.notes" rows="2" class="oak-input" :placeholder="labels.tankPosNoteHint"></textarea>
					</section>

					<router-link
						:to="`/tank-position/history/${encodeURIComponent(tank.container)}`"
						class="oak-btn oak-btn-secondary w-full"
					>
						<Icon name="clock" :size="15" /> {{ labels.posHistTitle }}
						<span v-if="tank.moves" class="text-gray-400">· {{ fill(labels.posHistTimes, { n: tank.moves }) }}</span>
					</router-link>

					<!-- Gagal disimpan. Yang diketik TETAP di layar dan tombolnya tetap di
					     tempatnya: app ini tidak punya antrean kirim-belakangan (dihapus
					     2026-08-18, lihat data/send.js), jadi satu-satunya jawaban jujur adalah
					     "belum tersimpan, coba lagi" — bukan "tersimpan di HP". -->
					<div v-if="saveError" class="rounded-xl border border-red-200 bg-red-50 p-3">
						<p class="flex items-center gap-1.5 text-sm font-bold text-red-700">
							<Icon name="alert-circle" :size="15" /> {{ labels.error }}
						</p>
						<p class="mt-0.5 text-xs text-red-900">{{ saveError }}</p>
					</div>

					<div class="oak-footer space-y-1">
						<button
							class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
							:disabled="saving || !form.location_note"
							@click="save"
						>
							{{ saving ? "…" : fill(labels.tankPosSaveWith, { label: form.location_note.trim() || "—" }) }}
						</button>
						<p class="text-center text-[11px] text-gray-400">{{ labels.tankPosAutoStamp }}</p>
					</div>
				</template>
			</template>
		</template>
	</div>
</template>

<script setup>
import { computed, h, nextTick, onMounted, reactive, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { cachedResource } from "@/data/cache"
import { send, uploadPhoto, photoSrc } from "@/data/send"
import { useServerDraft } from "@/utils/serverDraft"
import { labels } from "@/utils/labels"
import { since, fmtDate, fmtDateTime } from "@/utils/surveyStatus"
import { daysFrom, fill, groupByDay, useSavedFilters } from "@/utils/listKit"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { usePhotoQueue } from "@/utils/photoQueue"
import { shootOrFallback } from "@/utils/camera"
import { setPreselect } from "@/utils/positionPick"
import Icon from "@/components/Icon.vue"
import PhotoTile from "@/components/PhotoTile.vue"
import PhotoMark from "@/components/PhotoMark.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import PositionTemplateChips from "@/components/PositionTemplateChips.vue"
import PositionJob from "@/components/PositionJob.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import OrderInfo from "@/components/list/OrderInfo.vue"
import ListSearch from "@/components/list/ListSearch.vue"
import StatPills from "@/components/list/StatPills.vue"
import FilterBar from "@/components/list/FilterBar.vue"
import FilterSheet from "@/components/list/FilterSheet.vue"
import DetailHeader from "@/components/list/DetailHeader.vue"

const route = useRoute()
const router = useRouter()


// ---- daftar ----
// Pil dan filter dikirim ke server, bukan disaring di klien — yang dijanjikan pil adalah
// angka penuh, dan menyaring satu halaman yang terlanjur diambil tidak akan sampai ke sana.
const PAGE = 20
const SHEET_DEFAULTS = { day: "", depot: "", principal: "", urgentOnly: false }
const SHEET_FIELDS = [
	{ key: "urgentOnly", type: "toggle", icon: "alert-triangle", label: labels.listUrgentOnly },
	{ key: "day", type: "date", label: labels.svChipDate },
	{ key: "depot", type: "chips", list: "depots", label: labels.svChipDepot },
	{ key: "principal", type: "select", list: "principals", label: labels.svChipPrincipal },
]
const f = useSavedFilters("tankpos", { ...SHEET_DEFAULTS, group: "", sort: "due" })
const sheetOpen = ref(false)

const activeChips = computed(() =>
	[
		f.day && { key: "day", label: labels.svChipDate, value: fmtDate(f.day) },
		f.depot && { key: "depot", label: labels.svChipDepot, value: f.depot },
		f.principal && { key: "principal", label: labels.svChipPrincipal, value: f.principal },
		f.urgentOnly && { key: "urgentOnly", label: "", value: labels.listUrgentOnly },
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
	Object.assign(f, SHEET_DEFAULTS, { group: "", sort: "due" })
	reload()
}

const items = ref([])
const total = ref(0)
const counts = ref({})
const options = ref({ depots: [], principals: [] })
const dayCounts = ref({})
const failed = ref(false)
const start = ref(0)

const boardRes = cachedResource({
	url: "container_depot.ess.container_position.position_board",
	method: "GET",
	makeParams: () => ({
		group: f.group || "",
		day: f.day || undefined,
		depot: f.depot || undefined,
		principal: f.principal || undefined,
		urgent_only: f.urgentOnly ? 1 : 0,
		sort: f.sort,
		start: start.value,
		page_length: PAGE,
		limit: 1, // daftar pendek papan lama tidak dibaca layar ini
	}),
	auto: true,
	onSuccess(data) {
		failed.value = false
		items.value = start.value ? [...items.value, ...(data?.items || [])] : data?.items || []
		total.value = data?.total || 0
		counts.value = data?.counts || {}
		options.value = { depots: data?.depots || [], principals: data?.principals || [] }
		dayCounts.value = data?.day_counts || {}
	},
	onError() {
		failed.value = true
	},
})

const pills = computed(() => [
	{ key: "", label: labels.tankPosStatAll, count: counts.value.all || 0, tone: "text-gray-900" },
	{ key: "located", label: labels.tankPosStatLocated, count: counts.value.located || 0, tone: "text-leaf-600" },
	{ key: "missing", label: labels.tankPosStatMissing, count: counts.value.missing || 0, tone: "text-gray-500" },
	{ key: "recheck", label: labels.tankPosStatRecheck, count: counts.value.recheck || 0, tone: "text-amber-600" },
])

// Grup per tanggal survey (server: `day_key`); yang dinyatakan mendesak di grupnya sendiri di
// atas semua tanggal. Merah = tenggatnya sudah tiba dan letaknya belum/perlu dicek.
const days = computed(() =>
	groupByDay(items.value, (r) => r.day_key, {
		hot: (r) => r.pos_state !== "located" && !!r.day_key && r.day_key !== "urgent" && daysFrom(r.day_key) <= 0,
	}).map((g) =>
		g.date === "urgent" ? { ...g, label: labels.lowSecUrgent, hot: true } : g.date ? g : { ...g, label: labels.listNoSurveyDate }
	)
)
const missingRows = computed(() => items.value.filter((r) => r.pos_state === "missing"))

function reload() {
	start.value = 0
	boardRes.reload()
}
function loadMore() {
	start.value = items.value.length
	boardRes.reload()
}
function setGroup(key) {
	f.group = key
	reload()
}
function toggleSort() {
	f.sort = f.sort === "far" ? "due" : "far"
	reload()
}
function bulkFrom(rows) {
	setPreselect(rows)
	router.push("/tank-position/bulk")
}

// Satu baris tank: nomor + letak + job (OrderInfo + PositionJob). Dipakai daftar dan hasil
// pencarian; render function di file yang sama karena ia tidak punya arti di luar layar ini.
const STATE = {
	missing: { label: labels.tankPosStatMissing, cls: "bg-gray-100 text-gray-600" },
	recheck: { label: labels.tankPosStatRecheck, cls: "bg-amber-100 text-amber-800" },
	located: { label: labels.tankPosStatLocated, cls: "bg-leaf-100 text-leaf-700" },
}
function rowLine(r) {
	if (!r.current_location) {
		return [labels.tankPosUnlocated, r.eir_in_date ? `${labels.tankPosEnteredAt} ${fmtDateTime(r.eir_in_date)}` : null]
	}
	return [r.current_location, `${labels.tankPosDicatat.toLowerCase()} ${since(r.location_updated_on)}`, r.location_updated_by]
}
const PosRow = ({ r }) => {
	const st = STATE[r.pos_state || (r.current_location ? "located" : "missing")]
	return h("li", null, [
		h("button", { type: "button", class: "oak-press flex min-h-[64px] w-full items-center gap-2 px-4 py-3 text-left", onClick: () => open(r.name, r) }, [
			h("span", { class: "block min-w-0 flex-1" }, [
				h(
					OrderInfo,
					{ title: r.container_no || r.name, principal: r.principal, meta: rowLine(r) },
					() => h("span", { class: `oak-chip shrink-0 ${st.cls}` }, st.label)
				),
				h(PositionJob, { row: r }),
			]),
			h(Icon, { name: "chevron-right", size: 18, class: "shrink-0 text-gray-300" }),
		]),
	])
}
PosRow.props = ["r"]

// ---- pencarian ----
const search = ref("")
const searchRes = cachedResource({
	url: "container_depot.ess.container_position.tank_search",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 20 }),
})
const searchRows = computed(() => (search.value.trim() ? searchRes.data?.items || [] : []))
function onSearch() {
	if (search.value.trim()) searchRes.reload()
}

// ---- satu tank ----
const tank = ref(null)
const pending = ref(false)
const saved = ref(null)
const form = reactive({ location_note: "", notes: "", photos: [] })
// Keterangan per foto, dikunci pada url-nya — di luar `form.photos` karena yang dikirim
// dirakit saat simpan, dan grid/lightbox tetap membaca deretan url apa adanya.
const photoNotes = reactive({})
const photoUploading = ref(false)

const specLine = computed(() =>
	[tank.value?.principal, [tank.value?.container_type, tank.value?.size].filter(Boolean).join(" "),
		tank.value?.depot ? `depot ${tank.value.depot}` : null]
		.filter(Boolean)
		.join(" · ")
)

const detailRes = cachedResource({
	url: "container_depot.ess.container_position.tank_position",
	method: "GET",
	onSuccess(data) {
		pending.value = false
		tank.value = data
		// Diisi dengan yang sudah tercatat: kebanyakan pembaruan adalah koreksi kecil atas
		// kalimat yang ada, bukan kalimat baru yang diketik satu tangan di samping tumpukan.
		form.location_note = data.location_note || ""
		form.notes = ""
		// Foto TIDAK diwarisi dari pencatatan sebelumnya. Tiap pencatatan adalah catatan atas
		// apa yang dilihat saat itu, jadi membawa foto kemarin ke hari ini berarti mengarsipkan
		// gambar tumpukan yang mungkin sudah ditinggalkan tank-nya.
		form.photos = []
		for (const url of Object.keys(photoNotes)) delete photoNotes[url]
		restoreDraft()
	},
	onError(err) {
		pending.value = false
		tank.value = null
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})

// Baris papan yang ditekan — job-nya ditampilkan lagi di layar satu tank. Kosong saat tank
// dibuka dari pencarian atau deep link: tidak semua tank sedang punya job.
const job = ref(null)

function open(container, row = null) {
	job.value = row?.survey_order ? row : null
	saved.value = null
	saveError.value = ""
	pending.value = true
	tank.value = { container, container_no: container, history: [] }
	detailRes.submit({ container })
}

function backToList() {
	tank.value = null
	saved.value = null
	pending.value = false
	search.value = ""
	reload()
}

// "Selesai" berarti selesai — keluar dari layar ini, bukan kembali ke formulir tank yang baru
// saja dicatat (yang dilakukan `saved = null`, dan terbaca sebagai tombol yang tidak berbuat
// apa-apa: kartu hijau hilang, isian yang sama muncul lagi).
//
// Ke mana keluarnya tergantung dari mana masuknya. Yang datang lewat tautan `?c=` sedang di
// tengah pekerjaan lain — membaca kartu tank di Monitor, menutup survey — dan yang mereka
// minta hanyalah mencatat letaknya; mengembalikan mereka ke papan Letak Tank berarti jalan
// kembali harus ditempuh sendiri. Yang masuk dari papan ini memang sedang mencatat tank satu
// per satu, jadi papan itulah tempat kembalinya.
function finish() {
	if (cameFromDeepLink.value && window.history.length > 1) {
		router.back()
		return
	}
	backToList()
}

// Isian yang belum disimpan (letak, catatan, foto + keterangannya) tersimpan otomatis di server
// per tank, dan muncul lagi kalau layar ini ditutup lalu dibuka ulang.
const draft = useServerDraft(() => (tank.value?.container ? `position:${tank.value.container}` : null))
let restoring = true
async function restoreDraft() {
	restoring = true
	const d = await draft.load()
	if (d) {
		form.location_note = d.location_note ?? form.location_note
		form.notes = d.notes || ""
		form.photos = d.photos || []
		Object.assign(photoNotes, d.captions || {})
	}
	nextTick(() => { restoring = false })
}
watch([() => form.location_note, () => form.notes, () => form.photos, photoNotes], () => {
	if (!restoring && !pending.value) {
		draft.save({ location_note: form.location_note, notes: form.notes, photos: form.photos, captions: photoNotes })
	}
}, { deep: true })

// ---- simpan ----
const saving = ref(false)
const saveError = ref("")

async function save() {
	if (saving.value || !tank.value || !form.location_note) return
	saving.value = true
	saveError.value = ""
	const c = tank.value.container
	try {
		const res = await send({
			url: "container_depot.ess.container_position.position_record",
			payload: {
				container: c,
				location_note: form.location_note,
				notes: form.notes || undefined,
				// `{photo, caption}` — server menormalkan kedua bentuknya (`_coerce_photos`).
				// Ref `local:` yang masih terparkir diunggah `send` sebelum POST berangkat;
				// penukarannya menelusuri objek bersarang juga (`collectLocalRefs`).
				photos: form.photos.length
					? form.photos.map((url) => ({ photo: url, caption: (photoNotes[url] || "").trim() }))
					: undefined,
			},
		})
		draft.clear()
		saved.value = { ...res, container: tank.value.container_no || c }
	} catch (e) {
		saveError.value = e?.message || labels.error
		toast.error(saveError.value)
	} finally {
		saving.value = false
	}
}

// ---- foto ----
function removePhoto(i) {
	const [url] = form.photos.splice(i, 1)
	// Keterangan yatim akan ikut terkirim menempel pada foto berikutnya yang ber-url sama.
	if (url) delete photoNotes[url]
}
async function onPhotos(e) {
	const files = Array.from(e.target.files || [])
	e.target.value = "" // supaya file yang sama bisa dipilih lagi
	await addPhotos(files)
}
const camInput = ref(null)
function openCameraOrFallback() {
	return shootOrFallback(camInput, (file) => addPhotos([file]))
}
const photoQueue = usePhotoQueue()
async function addPhotos(files) {
	if (!files.length) return false
	// `last` adalah jawaban untuk viewfinder: strip di dalam kamera menandai jepretan ini dari
	// nilai yang dikembalikan (lihat utils/camera.js), jadi kegagalan yang ditelan di sini akan
	// tampil sebagai "terkirim" pada foto yang tidak ke mana-mana.
	let last = false
	photoQueue.clearFailed()
	photoUploading.value = true
	try {
		// Satu per satu dan ditambahkan begitu mendarat, supaya grid terisi selagi sisanya
		// masih naik — di 3G yard, empat foto sekaligus adalah penantian yang nyata.
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				last = await uploadPhoto(f)
				form.photos.push(last)
				photoQueue.done(id)
			} catch {
				last = false
				toast.error(labels.error)
				photoQueue.fail(id)
			}
		}
	} finally {
		photoUploading.value = false
	}
	return last
}

// Deep link: `/tank-position?c=TNKU1234567` langsung membuka tank itu — bentuk yang dipakai
// tautan dari layar survey, Monitor, dan riwayat posisi.
// Dicatat sebelum query-nya dihapus: `router.replace` di bawah membuang `?c=` supaya reload
// tidak membuka ulang tank yang sudah ditinggalkan, jadi sesudahnya tidak ada lagi jejak
// bahwa layar ini dibuka dari layar lain. `finish()` membutuhkannya.
const cameFromDeepLink = ref(false)

onMounted(() => {
	const c = route.query.c
	if (!c) return
	cameFromDeepLink.value = true
	router.replace({ query: {} })
	open(String(c))
})
</script>
