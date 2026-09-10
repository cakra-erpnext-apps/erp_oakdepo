<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- =================== PAPAN + PENCARIAN =================== -->
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

			<div class="relative">
				<Icon name="search" :size="18" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
				<input
					v-model="search"
					type="search"
					:placeholder="labels.tankPosSearch"
					class="oak-input pl-10 pr-10 uppercase"
					@input="onSearchInput"
				/>
				<button
					v-if="search"
					class="oak-press absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-gray-400"
					:aria-label="labels.tplCancel"
					@click="clearSearch"
				>
					<Icon name="x" :size="16" />
				</button>
			</div>

			<!-- Hasil pencarian menggantikan papan: yang mengetik nomor tank sedang mencari satu
			     tank, bukan sedang membaca ringkasan depo. -->
			<template v-if="search.trim()">
				<ul v-if="searchRows.length" class="oak-card divide-y divide-gray-100 overflow-hidden">
					<li v-for="r in searchRows" :key="r.name">
						<button
							type="button"
							class="flex min-h-[60px] w-full items-center gap-3 px-4 py-3 text-left transition active:bg-gray-50"
							@click="open(r.name)"
						>
							<span class="oak-icon-tile h-10 w-10 shrink-0" :class="r.current_location ? 'bg-leaf-50 text-leaf-600' : 'bg-gray-100 text-gray-400'">
								<Icon :name="r.current_location ? 'map-pin' : 'help-circle'" :size="16" />
							</span>
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm font-extrabold text-gray-900">{{ r.container_no || r.name }}</span>
								<span class="block truncate text-[11px] text-gray-500">{{ searchLine(r) }}</span>
							</span>
							<span v-if="r.current_location" class="oak-chip shrink-0 bg-gray-100 font-mono text-gray-600">{{ r.current_location }}</span>
							<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
						</button>
					</li>
				</ul>
				<div v-else-if="!searchRes.loading" class="oak-card p-8 text-center text-sm text-gray-400">
					{{ labels.tankPosEmpty }}
				</div>
			</template>

			<template v-else>
				<!-- Empat angka. "Perlu dicek" berdiri sendiri dari "Belum" karena keduanya
				     pekerjaan yang berbeda: yang satu mengisi kekosongan, yang lain memeriksa
				     jawaban yang mungkin sudah bohong. -->
				<div class="grid grid-cols-4 gap-1.5">
					<button
						v-for="s in stats"
						:key="s.key"
						class="oak-press flex min-h-[68px] flex-col items-center justify-center rounded-xl border px-1 py-2 transition"
						:class="pillClass(s)"
						:aria-pressed="group === s.key"
						@click="setGroup(s.key)"
					>
						<span class="text-lg font-extrabold leading-none" :class="group === s.key ? 'text-brand-700' : s.tone">
							{{ s.count }}
						</span>
						<span class="mt-1 truncate text-[11px] font-semibold" :class="group === s.key ? 'text-brand-700' : 'text-gray-500'">
							{{ s.label }}
						</span>
					</button>
				</div>

				<div v-if="boardRes.loading && !board" class="oak-card space-y-3 p-4">
					<div class="oak-skeleton h-4 w-2/3"></div>
					<div class="oak-skeleton h-4 w-1/2"></div>
				</div>

				<!-- Tidak ada pekerjaan tersisa. Kalimat keduanya penting: tanpa itu layar kosong
				     terbaca sebagai layar rusak, padahal posisi memang banyak tercatat sendiri. -->
				<div
					v-else-if="board && !board.recheck.length && !board.missing.length && !board.today.length && !board.located.length"
					class="oak-card flex flex-col items-center gap-2 p-8 text-center"
				>
					<span class="oak-icon-tile h-12 w-12 bg-leaf-50 text-leaf-500"><Icon name="check-circle" :size="24" /></span>
					<p class="text-sm font-bold text-gray-900">{{ labels.tankPosBoardEmpty }}</p>
					<p class="text-xs text-gray-500">{{ labels.tankPosBoardEmptyHint }}</p>
				</div>

				<template v-else-if="board">
					<!-- Perlu dicek ulang -->
					<section v-if="board.recheck.length" class="space-y-1.5">
						<div class="flex items-baseline justify-between gap-2 px-1">
							<p class="text-xs font-bold text-gray-500">{{ labels.tankPosSecRecheck }} · {{ board.counts.recheck }}</p>
							<p class="truncate text-[11px] text-gray-400">
								{{ fill(labels.tankPosSecRecheckHint, { n: board.recheck_days }) }}
							</p>
						</div>
						<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
							<li v-for="r in board.recheck" :key="r.name">
								<button type="button" class="flex min-h-[60px] w-full items-center gap-3 px-4 py-3 text-left transition active:bg-gray-50" @click="open(r.name)">
									<span class="oak-icon-tile h-10 w-10 shrink-0 bg-amber-50 text-amber-600"><Icon name="flag" :size="17" /></span>
									<span class="min-w-0 flex-1">
										<span class="block truncate font-mono text-sm font-extrabold text-gray-900">{{ r.container_no || r.name }}</span>
										<span class="block truncate text-[11px] text-gray-500">{{ recheckLine(r) }}</span>
									</span>
									<span class="oak-chip shrink-0 bg-gray-100 font-mono text-gray-600">{{ r.current_location }}</span>
									<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
								</button>
							</li>
						</ul>
					</section>

					<!-- Belum terdata -->
					<section v-if="board.missing.length" class="space-y-1.5">
						<div class="flex items-baseline justify-between gap-2 px-1">
							<p class="text-xs font-bold text-gray-500">{{ labels.tankPosSecMissing }} · {{ board.counts.missing }}</p>
							<button class="oak-press -my-1 shrink-0 rounded-lg px-2 py-2 text-xs font-bold text-brand-600" @click="bulkFrom(board.missing)">
								{{ labels.bulkOpen }}
							</button>
						</div>
						<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
							<li v-for="r in board.missing" :key="r.name" class="flex min-h-[60px] items-center gap-3 px-4 py-3">
								<span class="oak-icon-tile h-10 w-10 shrink-0 bg-gray-100 text-gray-400"><Icon name="help-circle" :size="17" /></span>
								<div class="min-w-0 flex-1">
									<p class="truncate font-mono text-sm font-extrabold text-gray-900">{{ r.container_no || r.name }}</p>
									<p class="truncate text-[11px] text-gray-500">{{ missingLine(r) }}</p>
								</div>
								<button class="oak-btn oak-btn-secondary min-h-[44px] shrink-0 px-4 text-xs" @click="open(r.name)">
									{{ labels.tankPosRecordBtn }}
								</button>
							</li>
						</ul>
						<button
							v-if="board.counts.missing > board.missing.length"
							class="oak-btn oak-btn-secondary w-full"
							@click="showAllMissing"
						>
							{{ fill(labels.tankPosSecMore, { n: board.counts.missing - board.missing.length }) }}
						</button>
					</section>

					<!-- Semua yang sudah terdata, dibuka dari yang paling basi. Hanya muncul saat
					     pil "Terdata" ditekan: di tampilan pembuka ia bukan pekerjaan, dan daftar
					     ratusan baris di puncak layar mengubur dua daftar yang memang pekerjaan. -->
					<section v-if="board.located.length" class="space-y-1.5">
						<div class="flex items-baseline justify-between gap-2 px-1">
							<p class="text-xs font-bold text-gray-500">{{ labels.tankPosStatLocated }} · {{ board.counts.located }}</p>
							<p class="truncate text-[11px] text-gray-400">{{ labels.tankPosSortStale }}</p>
						</div>
						<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
							<li v-for="r in board.located" :key="r.name">
								<button type="button" class="flex min-h-[60px] w-full items-center gap-3 px-4 py-3 text-left transition active:bg-gray-50" @click="open(r.name)">
									<span class="oak-icon-tile h-10 w-10 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="map-pin" :size="17" /></span>
									<span class="min-w-0 flex-1">
										<span class="block truncate font-mono text-sm font-extrabold text-gray-900">{{ r.container_no || r.name }}</span>
										<span class="block truncate text-[11px] text-gray-500">{{ recheckLine(r) }}</span>
									</span>
									<span class="oak-chip shrink-0 bg-gray-100 font-mono text-gray-600">{{ r.current_location }}</span>
									<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
								</button>
							</li>
						</ul>
					</section>

					<!-- Terdata hari ini — bukan pekerjaan, melainkan bukti bahwa layar ini dipakai. -->
					<section v-if="board.today.length" class="space-y-1.5">
						<p class="px-1 text-xs font-bold text-gray-500">{{ labels.tankPosSecToday }} · {{ board.today.length }}</p>
						<ul class="oak-card divide-y divide-gray-100 overflow-hidden">
							<li v-for="r in board.today" :key="r.name">
								<button type="button" class="flex min-h-[60px] w-full items-center gap-3 px-4 py-3 text-left transition active:bg-gray-50" @click="open(r.name)">
									<span class="oak-icon-tile h-10 w-10 shrink-0 bg-leaf-50 text-leaf-600"><Icon name="check-circle" :size="17" /></span>
									<span class="min-w-0 flex-1">
										<span class="block truncate font-mono text-sm font-extrabold text-gray-900">{{ r.container_no || r.name }}</span>
										<span class="block truncate text-[11px] text-gray-500">{{ todayLine(r) }}</span>
									</span>
									<span class="oak-chip shrink-0 bg-gray-100 font-mono text-gray-600">{{ r.current_location }}</span>
									<Icon name="chevron-right" :size="18" class="shrink-0 text-gray-300" />
								</button>
							</li>
						</ul>
					</section>
				</template>
			</template>
		</template>

		<!-- =================== SATU TANK =================== -->
		<template v-else>
			<div class="flex items-center gap-2">
				<button class="oak-press flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-gray-500" :aria-label="labels.backBtn" @click="backToList">
					<Icon name="chevron-left" :size="22" />
				</button>
				<h1 class="min-w-0 flex-1 truncate text-lg font-extrabold tracking-tight text-gray-900">
					{{ labels.tankPosTitle }}
				</h1>
				<span v-if="tank.located && !tank.fresh" class="oak-chip shrink-0 bg-amber-100 text-amber-800">
					{{ labels.tankPosStale }}
				</span>
			</div>

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
					<button class="oak-btn oak-btn-secondary min-h-[48px] flex-1" @click="saved = null">{{ labels.tankPosDone }}</button>
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
										@click="openLightbox(form.photos.map(photoSrc), i)"
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
import { computed, onMounted, onBeforeUnmount, reactive, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { cachedResource } from "@/data/cache"
import { send, uploadPhoto, photoSrc } from "@/data/send"
import { labels } from "@/utils/labels"
import { since, fmtDateTime } from "@/utils/surveyStatus"
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

const route = useRoute()
const router = useRouter()

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}

// ---- papan ----
const boardLimit = ref(8)
// Pil yang sedang ditekan: "" = tampilan pembuka (tiga daftar pendek), selain itu satu daftar
// utuh. Dikirim ke server, bukan disaring di klien — yang dijanjikan pil adalah angka penuh,
// dan menyaring delapan baris yang terlanjur diambil tidak akan pernah sampai ke angka itu.
const group = ref("")
const boardRes = cachedResource({
	url: "container_depot.ess.container_position.position_board",
	method: "GET",
	makeParams: () => ({ limit: boardLimit.value, group: group.value || "" }),
	auto: true,
})
const board = computed(() => (boardRes.data?.success ? boardRes.data : null))

const stats = computed(() => {
	const c = board.value?.counts || { all: 0, located: 0, missing: 0, recheck: 0 }
	return [
		{ key: "all", label: labels.tankPosStatAll, count: c.all, tone: "text-gray-900" },
		{ key: "located", label: labels.tankPosStatLocated, count: c.located, tone: "text-leaf-600" },
		{ key: "missing", label: labels.tankPosStatMissing, count: c.missing, tone: "text-gray-500" },
		{ key: "recheck", label: labels.tankPosStatRecheck, count: c.recheck, tone: "text-amber-600" },
	]
})
function pillClass(s) {
	if (group.value === s.key) return "border-brand-500 bg-brand-500/10"
	if (s.key === "recheck" && s.count) return "border-amber-300 bg-amber-50"
	return "border-gray-200 bg-paper"
}
// Menekan pil yang sudah aktif mengembalikannya ke tampilan pembuka. Di HP itu jalan keluar
// yang paling dekat dengan jempol — tanpanya satu-satunya cara kembali adalah menemukan pil
// "Semua" yang letaknya justru paling jauh.
function setGroup(key) {
	group.value = group.value === key || key === "all" ? "" : key
	boardRes.reload()
}
function showAllMissing() {
	group.value = "missing"
	boardRes.reload()
}
function bulkFrom(rows) {
	setPreselect(rows)
	router.push("/tank-position/bulk")
}

function recheckLine(r) {
	return [r.principal, `${labels.tankPosDicatat.toLowerCase()} ${since(r.location_updated_on)}`, r.location_updated_by]
		.filter(Boolean)
		.join(" · ")
}
function missingLine(r) {
	const entered = r.eir_in_date ? `${labels.tankPosEnteredAt} ${fmtDateTime(r.eir_in_date)}` : null
	return [r.principal, entered].filter(Boolean).join(" · ")
}
function todayLine(r) {
	const clock = String(r.location_updated_on || "").slice(11, 16)
	return [r.principal, clock, r.location_updated_by].filter(Boolean).join(" · ")
}

// ---- pencarian ----
const search = ref("")
const searchRes = cachedResource({
	url: "container_depot.ess.container_position.tank_search",
	method: "GET",
	makeParams: () => ({ search: search.value || "", page_length: 20 }),
})
const searchRows = computed(() => (search.value.trim() ? searchRes.data?.items || [] : []))
let searchTimer = null
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => search.value.trim() && searchRes.reload(), 300)
}
function clearSearch() {
	search.value = ""
}
function searchLine(r) {
	if (!r.current_location) return [r.principal, labels.bulkPrevNone].filter(Boolean).join(" · ")
	return [r.principal, since(r.location_updated_on)].filter(Boolean).join(" · ")
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
	},
	onError(err) {
		pending.value = false
		tank.value = null
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})

function open(container) {
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
	boardRes.reload()
}

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
onMounted(() => {
	const c = route.query.c
	if (!c) return
	router.replace({ query: {} })
	open(String(c))
})
onBeforeUnmount(() => clearTimeout(searchTimer))
</script>
