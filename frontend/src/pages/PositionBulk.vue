<template>
	<div class="mx-auto w-full max-w-lg space-y-3 md:max-w-2xl">
		<div class="flex items-center gap-2">
			<button
				class="oak-press flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-gray-500"
				:aria-label="labels.backBtn"
				@click="goBack"
			>
				<Icon name="chevron-left" :size="22" />
			</button>
			<h1 class="min-w-0 flex-1 truncate text-lg font-extrabold tracking-tight text-gray-900">
				{{ labels.bulkTitle }}
			</h1>
			<span v-if="picked.length" class="oak-chip shrink-0 bg-brand-100 text-brand-700">
				{{ picked.length }} {{ labels.bulkTankWord }}
			</span>
		</div>

		<div class="flex gap-2 rounded-xl border border-blue-200 bg-blue-50 p-3">
			<Icon name="info" :size="16" class="mt-0.5 shrink-0 text-blue-600" />
			<div class="min-w-0">
				<p class="text-xs font-bold text-blue-900">{{ labels.bulkIntroTitle }}</p>
				<p class="mt-0.5 text-[11px] text-blue-800">{{ labels.bulkIntroHint }}</p>
			</div>
		</div>

		<!-- Posisi tujuan: satu kotak, berlaku untuk semua yang dipilih di bawah. -->
		<section class="oak-card space-y-2 border-brand-300 p-4">
			<div class="flex items-baseline justify-between gap-2">
				<p class="text-sm font-extrabold text-gray-900">{{ labels.bulkTarget }}</p>
				<p class="shrink-0 text-[11px] text-gray-400">{{ labels.bulkTargetAll }}</p>
			</div>
			<PositionTemplateChips v-model="target" :depot="depot" />
		</section>

		<!-- Tank yang dipilih -->
		<section class="oak-card overflow-hidden">
			<div class="flex items-center justify-between gap-2 px-4 pb-2 pt-3">
				<p class="text-sm font-extrabold text-gray-900">
					{{ labels.bulkPicked }} <span class="text-gray-400">{{ picked.length }}</span>
				</p>
				<button class="oak-btn oak-btn-secondary shrink-0 px-3 py-1.5 text-xs" @click="pickerOpen = !pickerOpen">
					<Icon name="plus" :size="14" /> {{ labels.bulkAdd }}
				</button>
			</div>

			<!-- Pencarian tank. Menggantikan tombol scan di mockup — scan tidak dikerjakan. -->
			<div v-if="pickerOpen" class="space-y-2 border-t border-gray-100 px-4 py-3">
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
				<p class="text-[11px] text-gray-400">{{ labels.bulkPickHint }}</p>
				<ul v-if="results.length" class="divide-y divide-gray-100">
					<li v-for="r in results" :key="r.name">
						<button
							type="button"
							class="flex w-full items-center gap-2 py-2.5 text-left transition active:bg-gray-50 disabled:opacity-40"
							:disabled="isPicked(r.name)"
							@click="pick(r)"
						>
							<span class="min-w-0 flex-1">
								<span class="block truncate font-mono text-sm font-bold text-gray-900">{{ r.container_no || r.name }}</span>
								<span class="block truncate text-[11px] text-gray-500">{{ prevLine(r) }}</span>
							</span>
							<Icon :name="isPicked(r.name) ? 'check' : 'plus'" :size="16" class="shrink-0 text-gray-400" />
						</button>
					</li>
				</ul>
			</div>

			<p v-if="!picked.length" class="px-4 pb-4 text-xs text-gray-500">{{ labels.bulkEmpty }}</p>
			<ul v-else class="divide-y divide-gray-100 border-t border-gray-100">
				<li v-for="t in picked" :key="t.name" class="flex items-center gap-3 px-4 py-3">
					<span class="oak-icon-tile h-6 w-6 shrink-0 bg-brand-500 text-white">
						<Icon name="check" :size="13" />
					</span>
					<div class="min-w-0 flex-1">
						<p class="truncate font-mono text-sm font-bold text-gray-900">{{ t.container_no || t.name }}</p>
						<p class="truncate text-[11px] text-gray-500">{{ prevLine(t) }}</p>
					</div>
					<button
						class="oak-press flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-gray-400"
						:aria-label="labels.tplCancel"
						@click="drop(t.name)"
					>
						<Icon name="x" :size="16" />
					</button>
				</li>
			</ul>
		</section>

		<!-- Satu foto menjelaskan ketiganya: yang difoto adalah tumpukannya, bukan tanknya. -->
		<section class="oak-card space-y-2 p-4">
			<div class="flex items-baseline justify-between gap-2">
				<p class="text-sm font-extrabold text-gray-900">{{ labels.tankPosPhotos }}</p>
				<p class="shrink-0 text-[11px] text-gray-400">{{ labels.bulkPhotoAll }}</p>
			</div>
			<div class="grid grid-cols-3 gap-2">
				<div v-for="(url, i) in photos" :key="i" class="relative aspect-square">
					<img :src="photoSrc(url)" class="h-full w-full rounded-lg border border-gray-200 object-cover" />
					<button
						type="button"
						class="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-full bg-black/70 text-white"
						:aria-label="labels.tplCancel"
						@click="photos.splice(i, 1)"
					>
						<Icon name="x" :size="16" />
					</button>
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

		<div class="oak-footer space-y-1">
			<button
				class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
				:disabled="!canSave || saving"
				@click="save"
			>
				{{ saving ? "…" : fill(labels.bulkSave, { n: picked.length, label: target.trim() || "—" }) }}
			</button>
			<p class="text-center text-[11px] text-gray-400">{{ labels.bulkSaveHint }}</p>
		</div>
	</div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from "vue"
import { useRouter } from "vue-router"
import { cachedResource } from "@/data/cache"
import { send, uploadPhoto, photoSrc } from "@/data/send"
import { labels } from "@/utils/labels"
import { toast } from "@/utils/toast"
import { usePhotoQueue } from "@/utils/photoQueue"
import { shootOrFallback } from "@/utils/camera"
import { takePreselect } from "@/utils/positionPick"
import Icon from "@/components/Icon.vue"
import PhotoTile from "@/components/PhotoTile.vue"
import PositionTemplateChips from "@/components/PositionTemplateChips.vue"

const router = useRouter()

const target = ref("")
const picked = ref([])
const photos = ref([])
const saving = ref(false)

// Depot yang template-nya ditawarkan: depot tank pertama yang dipilih. Tank dari dua depot
// dalam satu simpanan memang bisa terjadi lewat pencarian, tapi daftar template harus memilih
// satu yard — dan yard yang benar adalah yang sedang ditunjuk pekerjaan ini.
const depot = computed(() => picked.value[0]?.depot || "")

const canSave = computed(() => picked.value.length > 0 && target.value.trim().length > 0)

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}
function prevLine(t) {
	const who = t.principal ? `${t.principal} · ` : ""
	return who + (t.current_location ? fill(labels.bulkPrev, { label: t.current_location }) : labels.bulkPrevNone)
}

// --- pemilih tank ---
const pickerOpen = ref(true)
const query = ref("")
const searchRes = cachedResource({
	url: "container_depot.ess.container_position.tank_search",
	method: "GET",
	makeParams: () => ({ search: query.value || "", page_length: 8 }),
})
const results = computed(() => (query.value.trim() ? searchRes.data?.items || [] : []))
let timer = null
function onSearch() {
	clearTimeout(timer)
	timer = setTimeout(() => query.value.trim() && searchRes.reload(), 300)
}
const isPicked = (name) => picked.value.some((t) => t.name === name)
function pick(r) {
	if (isPicked(r.name)) return
	picked.value.push(r)
	query.value = ""
}
function drop(name) {
	picked.value = picked.value.filter((t) => t.name !== name)
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
	// `last` adalah jawaban untuk viewfinder: strip di dalam kamera menandai jepretan ini dari
	// nilai yang dikembalikan (lihat utils/camera.js), jadi kegagalan yang ditelan di sini akan
	// tampil sebagai "terkirim" pada foto yang tidak ke mana-mana.
	let last = false
	photoQueue.clearFailed()
	photoUploading.value = true
	try {
		for (const f of files) {
			const id = photoQueue.add(f)
			try {
				last = await uploadPhoto(f)
				photos.value.push(last)
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
		const res = await send({
			url: "container_depot.ess.container_position.position_record_bulk",
			payload: {
				containers: JSON.stringify(picked.value.map((t) => t.name)),
				location_note: target.value.trim(),
				photos: photos.value.length ? photos.value : undefined,
			},
		})
		// Gagal sebagian dilaporkan apa adanya. Yang tercatat tetap tercatat — membatalkan
		// semuanya karena satu tank sudah keluar depo berarti membuang pekerjaan yang benar,
		// dan operatornya sudah berjalan pergi.
		const failed = res?.failed || []
		if (failed.length) toast.error(fill(labels.bulkPartial, { n: failed.length }))
		else toast.success(labels.tankPosSaved, { title: target.value.trim() })
		router.push("/tank-position")
	} catch (e) {
		toast.error(e?.message || labels.error)
	} finally {
		saving.value = false
	}
}

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/tank-position")
}

// Dibuka dari daftar "belum terdata" dengan tank-nya sudah terpilih — di situlah orang
// memutuskan untuk mencatat beberapa sekaligus. Barisnya dititipkan utuh (utils/positionPick),
// bukan dicari ulang dari nomornya.
onMounted(() => {
	const rows = takePreselect()
	if (!rows.length) return
	picked.value = rows
	pickerOpen.value = false
})
onBeforeUnmount(() => clearTimeout(timer))
</script>
