<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<div class="flex items-center justify-between">
			<div class="min-w-0">
				<h1 class="truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ labels.tankPosTitle }}
				</h1>
				<p v-if="tank" class="truncate font-mono text-[11px] text-gray-500">
					{{ tank.container_no || tank.container }}
				</p>
				<p v-else class="text-sm text-gray-500">{{ labels.tankPosHint }}</p>
			</div>
			<button v-if="tank" class="oak-btn oak-btn-secondary shrink-0 px-3 py-2" @click="backToList">
				<Icon name="arrow-left" :size="16" /> {{ labels.surveyPosBack }}
			</button>
		</div>

		<!-- =================== SEARCH ===================
		     A tank number is the only thing anyone standing in a yard has to hand, so it is the
		     only thing this searches on. The second tab is the list this feature exists to
		     empty: tanks nobody has ever recorded. -->
		<section v-if="!tank" class="oak-section space-y-3">
			<div class="flex gap-2">
				<input
					v-model="search"
					class="oak-input uppercase"
					:placeholder="labels.tankPosSearch"
					autocapitalize="characters"
					autocorrect="off"
					autocomplete="off"
					spellcheck="false"
					enterkeyhint="search"
					@input="onSearchInput"
					@keyup.enter="reload"
				/>
				<button class="oak-btn oak-btn-secondary shrink-0 px-3" @click="reload">
					<Icon name="search" :size="16" />
				</button>
			</div>

			<!-- Empat tab tidak muat dibagi rata di layar HP tanpa memotong "Belum Terdata",
			     jadi barisnya menggeser ke samping seperti baris status di daftar lain. -->
			<div class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
				<button
					v-for="f in FILTERS"
					:key="f.key"
					class="oak-toggle flex shrink-0 items-center justify-center gap-1.5 px-3 text-xs"
					:class="filter === f.key ? 'oak-toggle-on' : 'oak-toggle-off'"
					@click="setFilter(f.key)"
				>
					{{ f.label }}
				</button>
			</div>

			<!-- Antrean "cek letak tank": tank yang hari surveinya sudah dijadwalkan tapi
			     letaknya belum pernah dicatat — atau catatannya lebih tua dari booking yang
			     menjadwalkannya, yang artinya sama saja: tidak ada yang benar-benar melihat
			     tank itu sejak ada alasan untuk mencarinya. Diurut memakai tenggat yang sama
			     dengan worklist lain, jadi yang surveinya paling dekat berdiri paling atas. -->
			<p v-if="filter === 'orders'" class="rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800">
				{{ labels.tankPosOrdersHint }}
			</p>

			<SkeletonList v-if="loading && !items.length" :action="false" />
			<p v-else-if="!items.length" class="py-6 text-center text-sm text-gray-400">
				{{ EMPTY_TEXT[filter] || labels.tankPosEmpty }}
			</p>
			<!-- Tab Riwayat: satu baris = satu pencatatan, bukan satu tank. Nomor tank tetap di
			     depan karena itu yang dicari mata, tapi yang dijawab baris ini adalah "apa yang
			     dilaporkan, kapan, oleh siapa" — dan fotonya langsung terlihat, karena riwayat
			     berisi kalimat-kalimat telanjang memaksa orang membuka satu per satu untuk tahu
			     ada gambarnya atau tidak. -->
			<ul v-else-if="filter === 'history'" class="divide-y divide-gray-100">
				<li v-for="h in items" :key="h.name">
					<button class="oak-press w-full py-2.5 text-left" @click="open(h.container)">
						<div class="flex items-baseline justify-between gap-2">
							<p class="truncate font-bold text-gray-900">{{ h.container_no || h.container }}</p>
							<span class="shrink-0 text-[11px] text-gray-400">{{ since(h.recorded_on) }}</span>
						</div>
						<p class="mt-0.5 flex items-start gap-1.5 whitespace-pre-line text-[13px] text-gray-700">
							<Icon name="map-pin" :size="13" class="mt-0.5 shrink-0 text-brand-500" />
							{{ h.location_note }}
						</p>
						<p v-if="h.notes" class="truncate text-[11px] text-gray-400">{{ h.notes }}</p>
						<p class="mt-0.5 flex items-center gap-1 truncate text-[11px] text-gray-400">
							<Icon name="clock" :size="11" class="shrink-0" />
							{{ [fmtDateTime(h.recorded_on), h.recorded_by].filter(Boolean).join(" · ") }}
						</p>
						<div v-if="h.photos && h.photos.length" class="mt-1.5 flex flex-wrap gap-1.5">
							<img
								v-for="(url, j) in h.photos"
								:key="url"
								:src="url"
								class="h-14 w-14 rounded-md border border-gray-200 object-cover"
								loading="lazy"
								@click.stop="openLightbox(h.photos, j)"
							/>
						</div>
					</button>
				</li>
			</ul>
			<ul v-else class="divide-y divide-gray-100">
				<li v-for="r in items" :key="r.name">
					<button class="oak-press flex w-full items-center gap-3 py-2.5 text-left" @click="open(r.name)">
						<span class="oak-icon-tile h-9 w-9 shrink-0" :class="r.located ? 'bg-brand-50 text-brand-600' : 'bg-red-50 text-red-500'">
							<Icon :name="r.located ? 'map-pin' : 'help-circle'" :size="16" />
						</span>
						<div class="min-w-0 flex-1">
							<p class="truncate font-semibold text-gray-900">{{ r.container_no || r.name }}</p>
							<p class="truncate text-[11px]" :class="r.located ? 'text-gray-600' : 'text-red-500'">
								{{ r.located ? r.current_location : labels.tankPosUnlocated }}
							</p>
							<p v-if="r.target_survey_on || r.target_lift_on" class="mt-1 flex items-center">
								<LiftOnBadge :survey="r.target_survey_on" :target="r.target_lift_on" />
							</p>
						</div>
						<!-- The age of the answer, not just the answer. A position recorded in June
						     is a guess; one from this morning is an instruction. -->
						<span v-if="r.located" class="oak-chip shrink-0" :class="r.fresh ? 'bg-leaf-100 text-leaf-700' : 'bg-amber-100 text-amber-800'">
							{{ since(r.location_updated_on) }}
						</span>
						<Icon name="chevron-right" :size="16" class="shrink-0 text-gray-300" />
					</button>
				</li>
			</ul>
			<!-- Ditambahkan ke bawah, bukan pindah halaman: orang yang meng-scroll daftar tank
			     tidak memegang nomor halaman di kepalanya. -->
			<button
				v-if="items.length && items.length < total"
				class="oak-btn oak-btn-secondary w-full py-2.5"
				:disabled="loading"
				@click="loadMore"
			>
				{{ loading ? "…" : labels.surveyListMore }}
			</button>
			<p v-if="items.length" class="text-center text-xs text-gray-400">
				{{ items.length }} / {{ total }} {{ labels.tankPosCount }}
			</p>
		</section>

		<!-- =================== ONE TANK =================== -->
		<SkeletonDetail v-else-if="pending" :cells="4" :sections="2" />
		<template v-else-if="tank">
			<section class="oak-card space-y-2 p-4">
				<p class="truncate text-2xl font-extrabold tracking-tight text-gray-900">
					{{ tank.container_no || tank.container }}
				</p>
				<p v-if="tank.principal" class="truncate text-sm font-semibold text-gray-600">
					{{ tank.principal }}
				</p>
			</section>

			<section class="oak-card space-y-2 p-4" :class="tank.located ? '' : 'border-red-200 bg-red-50'">
				<p class="text-[11px] uppercase tracking-wide text-gray-400">{{ labels.tankPosCurrent }}</p>
				<template v-if="tank.located">
					<p class="flex items-start gap-1.5 whitespace-pre-line text-base font-bold text-gray-900">
						<Icon name="map-pin" :size="16" class="mt-1 shrink-0 text-brand-500" />
						{{ tank.location_note }}
					</p>
					<p class="text-xs text-gray-500">
						{{ since(tank.location_updated_on) }}
						<template v-if="tank.location_updated_by">
							· {{ labels.tankPosBy }} {{ tank.location_updated_by }}
						</template>
					</p>
					<p v-if="!tank.fresh" class="oak-chip bg-amber-100 text-amber-800">
						<Icon name="alert-triangle" :size="11" /> {{ labels.tankPosStale }}
					</p>
				</template>
				<template v-else>
					<p class="flex items-center gap-1.5 text-sm font-bold text-red-700">
						<Icon name="alert-triangle" :size="15" /> {{ labels.tankPosUnlocated }}
					</p>
					<p class="text-sm text-red-900">{{ labels.tankPosUnlocatedHint }}</p>
				</template>
			</section>

			<!-- The whole point of the screen: correct it, from wherever you are standing. -->
			<section class="oak-section space-y-3">
				<div class="flex items-center gap-2">
					<Icon name="edit-2" :size="16" class="text-brand-500" />
					<p class="oak-section-title">
						{{ tank.located ? labels.tankPosUpdate : labels.tankPosInput }}
					</p>
				</div>
				<div>
					<label class="oak-label">{{ labels.tankPosNewLabel }}</label>
					<textarea
						v-model.trim="form.location_note"
						rows="2"
						class="oak-input"
						:placeholder="labels.posLocationHint"
					/>
				</div>
				<div>
					<label class="oak-label">{{ labels.tankPosNote }}</label>
					<textarea
						v-model.trim="form.notes"
						rows="2"
						class="oak-input"
						:placeholder="labels.tankPosNoteHint"
					/>
				</div>

				<!-- Several photos, because one is rarely enough: the stack from the front, the
				     bay marking, the neighbouring tank. They go up the moment they are taken
				     (data/send.js) and a shot taken with no signal is parked and carried by the
				     save, so the operator keeps shooting either way. -->
				<div>
					<label class="oak-label">{{ labels.tankPosPhotos }}</label>
					<div class="grid grid-cols-3 gap-2">
						<div v-for="(url, i) in form.photos" :key="i" class="relative aspect-square">
							<img
								:src="photoSrc(url)"
								class="h-full w-full rounded-lg border border-gray-200 object-cover"
								@click="openLightbox(form.photos.map(photoSrc), i)"
							/>
							<button
								type="button"
								class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white shadow active:bg-black"
								aria-label="Hapus"
								@click="removePhoto(i)"
							>
								<Icon name="x" :size="16" />
							</button>
							<PhotoMark :photo="url" />
						</div>
						<PhotoTile v-for="it in photoQueue.items" :key="it.id" :item="it" tile="aspect-square w-full" />

						<!-- Two tiles, not one: the camera for the shot being taken right now,
						     the gallery for several already on the phone. -->
						<!-- The phone's own camera app, only ever reached as the fallback — see
						     utils/camera.js. -->
						<input
							ref="camInput"
							type="file"
							accept="image/*"
							capture="environment"
							multiple
							class="hidden"
							@change="onPhotos"
						/>
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
						<label
							class="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
						>
							<Icon v-if="photoUploading" name="loader" :size="22" class="animate-spin" />
							<template v-else>
								<Icon name="image" :size="22" />
								<span class="text-xs font-medium">{{ labels.photoGallery }}</span>
							</template>
							<input
								type="file"
								accept="image/*"
								multiple
								class="hidden"
								:disabled="photoUploading"
								@change="onPhotos"
							/>
						</label>
					</div>
					<p class="mt-1 text-[11px] text-gray-400">{{ labels.tankPosPhotoHint }}</p>
				</div>

				<p v-if="saveError" class="text-xs text-red-600">{{ saveError }}</p>
				<button
					class="oak-btn oak-btn-primary w-full py-3 text-base"
					:disabled="saving || !form.location_note"
					@click="save"
				>
					<Icon v-if="!saving" name="check-circle" :size="18" />
					{{ saving ? "…" : labels.tankPosSave }}
				</button>
			</section>

			<!-- The readings behind the current answer. A tank reported in three blocks this
			     morning is a tank nobody has actually found, and no single "current location"
			     can say that. -->
			<section v-if="(tank.history || []).length" class="oak-section space-y-2">
				<div class="flex items-center gap-2">
					<Icon name="clock" :size="16" class="text-gray-400" />
					<p class="oak-section-title">{{ labels.tankPosHistory }}</p>
				</div>
				<ul class="space-y-2 text-[13px]">
					<li v-for="(h, i) in tank.history" :key="h.name" class="flex items-start gap-2">
						<span class="mt-1.5 h-2 w-2 shrink-0 rounded-full" :class="i === 0 ? 'bg-brand-500' : 'bg-gray-300'" />
						<div class="min-w-0 flex-1">
							<p class="whitespace-pre-line font-medium text-gray-800">{{ h.location_note }}</p>
							<p class="text-xs text-gray-400">
								{{ fmtDateTime(h.recorded_on) }}
								<template v-if="h.recorded_by"> · {{ h.recorded_by }}</template>
							</p>
							<!-- Thumbnails right in the timeline. A history of bare sentences makes
							     the operator open every row to find out whether there is anything
							     to look at, which on a handset is the same as not having them. -->
							<div v-if="h.photos && h.photos.length" class="mt-1.5 flex flex-wrap gap-1.5">
								<img
									v-for="(url, j) in h.photos"
									:key="url"
									:src="url"
									class="h-14 w-14 cursor-pointer rounded-md border border-gray-200 object-cover"
									loading="lazy"
									@click="openLightbox(h.photos, j)"
								/>
							</div>
						</div>
					</li>
				</ul>
			</section>
		</template>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import Icon from "@/components/Icon.vue"
import PhotoMark from "@/components/PhotoMark.vue"
import PhotoTile from "@/components/PhotoTile.vue"
import { usePhotoQueue } from "@/utils/photoQueue"
import LiftOnBadge from "@/components/LiftOnBadge.vue"
import SkeletonList from "@/components/SkeletonList.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"
import { photoSrc, send, uploadPhoto } from "@/data/send"
import { openLightbox } from "@/utils/lightbox"
import { shootOrFallback } from "@/utils/camera"
import { fmtDateTime, since } from "@/utils/surveyStatus"

const route = useRoute()
const router = useRouter()

// ---- list ----
const items = ref([])
const total = ref(0)
const search = ref("")
const filter = ref("all")
// Daftar ini adalah SELURUH tank aktif di depot, bukan hasil pencarian: layar ini tempat
// letak tank dibetulkan, jadi yang sudah ada letaknya pun harus bisa dibuka tanpa mengetik
// apa pun. Satu depot punya ratusan tank, maka halaman berikutnya ditambahkan ke bawah —
// tanpa ini footer menyebut "312 tank" sementara cuma 50 yang bisa disentuh.
const PAGE = 50
const start = ref(0)

const FILTERS = computed(() => [
	{ key: "all", label: labels.tankPosFilterAll },
	{ key: "unlocated", label: labels.tankPosFilterUnlocated },
	{ key: "orders", label: labels.tankPosFilterOrders },
	{ key: "history", label: labels.tankPosFilterHistory },
])

const EMPTY_TEXT = computed(() => ({
	orders: labels.tankPosOrdersEmpty,
	history: labels.tankPosHistoryEmpty,
}))

function takeList(data) {
	// `start > 0` satu-satunya penanda bahwa ini "muat lagi", bukan kueri baru — resource-nya
	// sendiri tidak membedakan keduanya.
	items.value = start.value ? [...items.value, ...(data.items || [])] : data.items || []
	total.value = data.total || 0
}

const listRes = cachedResource({
	url: "container_depot.ess.container_position.tank_search",
	method: "GET",
	makeParams: () => ({
		search: search.value || "",
		only_unlocated: filter.value === "unlocated" ? 1 : 0,
		start: start.value,
		page_length: PAGE,
	}),
	auto: true,
	onSuccess: takeList,
})

// Sumber kedua, bukan parameter ketiga pada yang pertama: antrean ini menjawab pertanyaan
// yang berbeda ("tank mana yang ditunggu jawabannya") dan sudah diurut server memakai
// prioritas yang sama dengan worklist lain, sementara pencarian tank diurut dari yang paling
// basi. Menggabungkannya berarti satu endpoint dengan dua urutan dan satu pencarian yang
// diam-diam tidak berlaku.
const orderRes = cachedResource({
	url: "container_depot.ess.container_position.position_orders",
	method: "GET",
	makeParams: () => ({ start: start.value, page_length: PAGE }),
	onSuccess: takeList,
})

// Riwayat SELURUH tank, bukan riwayat satu tank. Inilah "history dan foto history" dari
// letak: setiap pencatatan berdiri sebagai baris tersendiri karena koreksi sepuluh menit
// kemudian adalah bacaan kedua, bukan penghapusan yang pertama — dan foto tiap bacaan ikut,
// dari sumber yang sama dengan layar tank-nya (container_position._attach_photos).
const historyRes = cachedResource({
	url: "container_depot.ess.container_position.position_history",
	method: "GET",
	makeParams: () => ({ search: search.value || "", start: start.value, page_length: PAGE }),
	onSuccess: takeList,
})

const activeRes = () =>
	({ orders: orderRes, history: historyRes })[filter.value] || listRes
const loading = computed(() => activeRes().loading)

let searchTimer = null
function reload() {
	clearTimeout(searchTimer)
	start.value = 0
	activeRes().reload()
}
function loadMore() {
	start.value = items.value.length
	activeRes().reload()
}
function onSearchInput() {
	clearTimeout(searchTimer)
	// Pencarian berlaku untuk daftar tank dan riwayatnya (keduanya dicari lewat nomor tank);
	// antrean adalah daftar tertutup yang isinya ditentukan jadwal, bukan ketikan.
	if (filter.value === "orders") return
	searchTimer = setTimeout(reload, 300)
}
function setFilter(key) {
	filter.value = key
	items.value = []
	reload()
}

// ---- one tank ----
const tank = ref(null)
const pending = ref(false)
const form = reactive({ location_note: "", notes: "", photos: [] })
const photoUploading = ref(false)

const detailRes = cachedResource({
	url: "container_depot.ess.container_position.tank_position",
	method: "GET",
	onSuccess(data) {
		pending.value = false
		tank.value = data
		// Pre-filled with what is already recorded: most updates are a small correction to the
		// existing note, not a fresh sentence typed one-handed next to a stack.
		form.location_note = data.location_note || ""
		form.notes = ""
		// Photos are NOT pre-filled from the last reading. Every reading is its own record of
		// what was seen at that moment (container_position.record_position always inserts), so
		// carrying yesterday's picture into today's would file a photo of a stack the tank may
		// well have left.
		form.photos = []
	},
	onError(err) {
		pending.value = false
		tank.value = null
		toast.error(err?.messages?.[0] || err?.message || labels.error)
	},
})

function open(container) {
	pending.value = true
	tank.value = { container, container_no: container, history: [] }
	detailRes.submit({ container })
}

function backToList() {
	tank.value = null
	pending.value = false
	start.value = 0
	listRes.reload()
}

// ---- save ----
const saving = ref(false)
const saveError = ref("")

async function save() {
	if (saving.value || !tank.value || !form.location_note) return
	saving.value = true
	saveError.value = ""
	const c = tank.value.container
	try {
		await send({
			url: "container_depot.ess.container_position.position_record",
			payload: {
				container: c,
				location_note: form.location_note,
				notes: form.notes || undefined,
				// A bare url list — the server coerces both shapes (`_coerce_photos`). Any
				// still-parked `local:` ref is uploaded by `send` before the post goes out.
				photos: form.photos.length ? form.photos : undefined,
			},
		})
		toast.success(labels.tankPosSaved, { title: tank.value.container_no || c })
		// Re-fetched rather than patched locally: the master's timestamp and the history are
		// the whole answer, and both are written by the server.
		open(c)
	} catch (e) {
		saveError.value = e?.message || labels.error
		toast.error(saveError.value)
	} finally {
		saving.value = false
	}
}

// ---- photos ----
function removePhoto(i) {
	form.photos.splice(i, 1)
}

async function onPhotos(e) {
	const files = Array.from(e.target.files || [])
	e.target.value = "" // so the same file can be picked again
	await addPhotos(files)
}

// In-app viewfinder: shutter -> upload, no camera-app confirm screen in between
// (utils/camera.js).
const camInput = ref(null)
function openCameraOrFallback() {
	return shootOrFallback(camInput, (file) => addPhotos([file]))
}

// Each photo shows itself while it goes up — see EirInForm for why.
const photoQueue = usePhotoQueue()

async function addPhotos(files) {
	if (!files.length) return
	photoQueue.clearFailed()
	photoUploading.value = true
	try {
		// One at a time and appended as they land, so the grid fills in while the rest are
		// still going up — on the yard's 3G a batch of four is a real wait.
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				form.photos.push(await uploadPhoto(f))
				photoQueue.done(id)
			} catch {
				toast.error(labels.error)
				photoQueue.fail(id)
			}
		}
	} finally {
		photoUploading.value = false
	}
}

// Deep link: `/tank-position?c=TNKU1234567` opens that tank straight away — the shape a QR
// scan or a link from the survey screen arrives in.
onMounted(() => {
	const c = route.query.c
	if (!c) return
	router.replace({ query: {} })
	open(String(c))
})
</script>
