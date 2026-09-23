<template>
	<div class="mx-auto w-full max-w-lg space-y-3 md:max-w-2xl">
		<div>
			<h1 class="text-xl font-extrabold tracking-tight text-gray-900">{{ labels.navLeak }}</h1>
			<p class="mt-0.5 text-xs text-gray-500">{{ labels.leakHint }}</p>
		</div>

		<!-- Tank -->
		<section class="oak-card space-y-2 p-4">
			<p class="text-sm font-extrabold text-gray-900">{{ labels.leakPickTank }}</p>
			<div v-if="tank" class="flex items-center gap-3">
				<p class="min-w-0 flex-1 truncate font-mono text-base font-extrabold text-gray-900">
					{{ tank.container_no || tank.name }}
				</p>
				<button class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs" @click="tank = null">
					{{ labels.leakChange }}
				</button>
			</div>
			<template v-else>
				<div class="relative">
					<Icon name="search" :size="16" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
					<input
						v-model="query"
						type="search"
						class="oak-input pl-9 uppercase"
						:placeholder="labels.tankPosSearch"
						@input="onSearch"
					/>
				</div>
				<ul v-if="results.length" class="divide-y divide-gray-100">
					<li v-for="r in results" :key="r.name">
						<button
							type="button"
							class="flex w-full items-center gap-2 py-2.5 text-left transition active:bg-gray-50"
							@click="pick(r)"
						>
							<span class="min-w-0 flex-1 truncate font-mono text-sm font-bold text-gray-900">{{ r.container_no || r.name }}</span>
							<span class="shrink-0 truncate text-[11px] text-gray-500">{{ r.principal }}</span>
						</button>
					</li>
				</ul>
				<p v-else-if="query.trim() && !searchRes.loading" class="text-xs text-gray-400">{{ labels.tankPosEmpty }}</p>
			</template>
		</section>

		<!-- Foto: tiap foto punya deskripsi (opsional) + tanda bocor (default tidak). -->
		<section class="oak-card space-y-2 p-4">
			<div class="flex items-baseline justify-between gap-2">
				<p class="text-sm font-extrabold text-gray-900">{{ labels.leakPhotos }}</p>
				<p class="shrink-0 text-[11px] text-gray-400">{{ labels.leakPhotosReq }}</p>
			</div>
			<div class="grid grid-cols-2 items-start gap-2 sm:grid-cols-3">
				<div v-for="(p, i) in photos" :key="p.photo" class="space-y-1">
					<div class="relative aspect-square">
						<img
							:src="photoSrc(p.photo)"
							class="h-full w-full rounded-lg border-2 object-cover"
							:class="p.is_leak ? 'border-red-500' : 'border-gray-200'"
							@click="openLightbox(photos.map((x) => ({ src: photoSrc(x.photo), caption: x.caption })), i)"
						/>
						<button
							type="button"
							class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white"
							:aria-label="labels.tplCancel"
							@click="photos.splice(i, 1)"
						>
							<Icon name="x" :size="16" />
						</button>
					</div>
					<input v-model="p.caption" type="text" class="oak-input px-2 py-1.5 text-xs" :placeholder="labels.photoCaption" />
					<label class="flex min-h-[36px] items-center gap-2 text-xs font-semibold" :class="p.is_leak ? 'text-red-600' : 'text-gray-600'">
						<input v-model="p.is_leak" type="checkbox" class="h-4 w-4" />
						{{ labels.leakFlag }}
					</label>
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
		</section>

		<!-- Remark umum, terpisah dari deskripsi per foto. -->
		<section class="oak-card space-y-2 p-4">
			<p class="text-sm font-extrabold text-gray-900">{{ labels.leakRemarks }}</p>
			<textarea v-model="remarks" rows="3" class="oak-input text-sm" :placeholder="labels.leakRemarksHint" />
		</section>

		<div class="oak-footer">
			<button
				class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
				:disabled="!canSave || saving"
				@click="save"
			>
				{{ saving ? "…" : labels.leakSave }}
			</button>
		</div>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from "vue"
import { cachedResource } from "@/data/cache"
import { send, uploadPhoto, photoSrc } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { openLightbox } from "@/utils/lightbox"
import { usePhotoQueue } from "@/utils/photoQueue"
import { shootOrFallback } from "@/utils/camera"
import Icon from "@/components/Icon.vue"
import PhotoTile from "@/components/PhotoTile.vue"

const tank = ref(null)
const photos = ref([]) // [{ photo, caption, is_leak }]
const remarks = ref("")
const saving = ref(false)
const canSave = computed(() => !!tank.value && photos.value.length > 0 && !photoUploading.value)

// --- pemilih tank ---
const query = ref("")
const searchRes = cachedResource({
	url: "container_depot.ess.leak_check.leak_tank_search",
	method: "GET",
	makeParams: () => ({ search: query.value || "", page_length: 8 }),
})
const results = computed(() => (query.value.trim() ? searchRes.data?.items || [] : []))
let timer = null
function onSearch() {
	clearTimeout(timer)
	timer = setTimeout(() => query.value.trim() && searchRes.reload(), 300)
}
function pick(r) {
	tank.value = r
	query.value = ""
}

// --- foto ---
const photoQueue = usePhotoQueue()
const photoUploading = ref(false)
const camInput = ref(null)
function openCameraOrFallback() {
	return shootOrFallback(camInput, (file) => addPhotos([file]))
}
async function onPhotos(e) {
	const files = Array.from(e.target.files || [])
	e.target.value = ""
	await addPhotos(files)
}
async function addPhotos(files) {
	if (!files.length) return false
	// `last` dibaca viewfinder kamera (utils/camera.js) untuk menandai jepretan gagal.
	let last = false
	photoQueue.clearFailed()
	photoUploading.value = true
	try {
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				last = await uploadPhoto(f)
				photos.value.push({ photo: last, caption: "", is_leak: false })
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

// --- simpan ---
async function save() {
	if (!canSave.value || saving.value) return
	saving.value = true
	try {
		await send({
			url: "container_depot.ess.leak_check.leak_record",
			payload: {
				container: tank.value.name,
				remarks: remarks.value.trim() || undefined,
				photos: photos.value.map((p) => ({ photo: p.photo, caption: p.caption.trim(), is_leak: p.is_leak ? 1 : 0 })),
			},
		})
		toast.success(labels.leakSaved, { title: tank.value.container_no || tank.value.name })
		tank.value = null
		photos.value = []
		remarks.value = ""
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		saving.value = false
	}
}

onBeforeUnmount(() => clearTimeout(timer))
</script>
