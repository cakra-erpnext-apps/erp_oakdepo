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

			<div class="grid grid-cols-2 gap-2">
				<button
					v-for="f in FILTERS"
					:key="f.key"
					class="oak-toggle flex items-center justify-center gap-1.5"
					:class="filter === f.key ? 'oak-toggle-on' : 'oak-toggle-off'"
					@click="setFilter(f.key)"
				>
					{{ f.label }}
				</button>
			</div>

			<SkeletonList v-if="listRes.loading && !items.length" :action="false" />
			<p v-else-if="!items.length" class="py-6 text-center text-sm text-gray-400">
				{{ labels.tankPosEmpty }}
			</p>
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
			<p v-if="items.length" class="text-center text-xs text-gray-400">
				{{ total }} {{ labels.tankPosCount }}
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
						</div>

						<!-- Two tiles, not one: the camera for the shot being taken right now,
						     the gallery for several already on the phone. -->
						<label
							class="flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-brand-300 bg-brand-50 text-brand-600 active:bg-brand-100"
						>
							<Icon v-if="photoUploading" name="loader" :size="22" class="animate-spin" />
							<template v-else>
								<Icon name="camera" :size="22" />
								<span class="text-xs font-medium">{{ labels.photoCamera }}</span>
							</template>
							<input
								type="file"
								accept="image/*"
								capture="environment"
								multiple
								class="hidden"
								:disabled="photoUploading"
								@change="onPhotos"
							/>
						</label>
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
import SkeletonList from "@/components/SkeletonList.vue"
import SkeletonDetail from "@/components/SkeletonDetail.vue"
import { cachedResource } from "@/data/cache"
import { photoSrc, send, uploadPhoto } from "@/data/send"
import { openLightbox } from "@/utils/lightbox"
import { fmtDateTime, since } from "@/utils/surveyStatus"

const route = useRoute()
const router = useRouter()

// ---- list ----
const items = ref([])
const total = ref(0)
const search = ref("")
const filter = ref("all")

const FILTERS = computed(() => [
	{ key: "all", label: labels.tankPosFilterAll },
	{ key: "unlocated", label: labels.tankPosFilterUnlocated },
])

const listRes = cachedResource({
	url: "container_depot.ess.container_position.tank_search",
	method: "GET",
	makeParams: () => ({
		search: search.value || "",
		only_unlocated: filter.value === "unlocated" ? 1 : 0,
		page_length: 50,
	}),
	auto: true,
	onSuccess(data) {
		items.value = data.items || []
		total.value = data.total || 0
	},
})

let searchTimer = null
function reload() {
	clearTimeout(searchTimer)
	listRes.reload()
}
function onSearchInput() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => listRes.reload(), 300)
}
function setFilter(key) {
	filter.value = key
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
	if (!files.length) return
	photoUploading.value = true
	try {
		// One at a time and appended as they land, so the grid fills in while the rest are
		// still going up — on the yard's 3G a batch of four is a real wait.
		for (const f of files) form.photos.push(await uploadPhoto(f))
	} catch {
		toast.error(labels.error)
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
