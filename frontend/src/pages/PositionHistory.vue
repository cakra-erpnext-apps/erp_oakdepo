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
				{{ labels.posHistTitle }}
			</h1>
			<span class="oak-chip shrink-0 bg-gray-100 font-mono text-gray-600">{{ container }}</span>
		</div>

		<div v-if="res.loading && !tank" class="oak-card space-y-3 p-4">
			<div class="oak-skeleton h-5 w-1/2"></div>
			<div class="oak-skeleton h-3 w-2/3"></div>
		</div>

		<template v-else-if="tank">
			<section class="oak-card space-y-3 p-4">
				<div class="min-w-0">
					<p class="truncate font-mono text-xl font-extrabold tracking-tight text-gray-900">
						{{ tank.container_no || tank.container }}
					</p>
					<p class="truncate text-xs text-gray-500">{{ headLine }}</p>
				</div>

				<!-- Tiga angka yang mengubah cara membaca posisi terakhirnya. Tank yang berpindah
				     empat kali minggu ini adalah tank yang catatannya cepat basi; yang berdiri di
				     tempat sama sejak masuk tidak perlu dicurigai walau catatannya tua. -->
				<div class="grid grid-cols-3 gap-2 border-t border-gray-100 pt-3">
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.tankPosCurrent }}</p>
						<p class="truncate font-mono text-sm font-bold text-gray-900">{{ tank.location_note || "—" }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.posHistMoveCount }}</p>
						<p class="truncate text-sm font-bold text-gray-900">{{ fill(labels.posHistTimes, { n: tank.moves ?? 0 }) }}</p>
					</div>
					<div class="min-w-0">
						<p class="text-[11px] text-gray-400">{{ labels.posHistInDepot }}</p>
						<p class="truncate text-sm font-bold text-gray-900">
							{{ tank.in_depot_days === null || tank.in_depot_days === undefined ? "—" : fill(labels.monitorDays, { n: tank.in_depot_days }) }}
						</p>
					</div>
				</div>
			</section>

			<section class="oak-card overflow-hidden">
				<div class="flex items-baseline justify-between gap-2 px-4 pb-2 pt-3">
					<p class="text-sm font-extrabold text-gray-900">{{ labels.posHistMoves }}</p>
					<p class="text-xs text-gray-400">{{ fill(labels.posHistLast, { n: history.length }) }}</p>
				</div>
				<p v-if="!history.length" class="px-4 pb-4 text-xs text-gray-500">{{ labels.tankPosHistoryEmpty }}</p>
				<ol v-else class="space-y-3 px-4 pb-4 pt-1">
					<li v-for="(h, i) in history" :key="h.name" class="relative flex gap-3">
						<span v-if="i < history.length - 1" class="absolute left-[5px] top-3 h-full w-px bg-gray-200"></span>
						<span
							class="relative mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
							:class="i === 0 ? 'bg-brand-500' : 'bg-leaf-500'"
						></span>
						<div class="min-w-0 flex-1">
							<p class="whitespace-pre-line font-mono text-sm font-bold text-gray-900">{{ h.location_note }}</p>
							<p class="truncate text-[11px] text-gray-400">{{ metaLine(h) }}</p>
							<p v-if="h.notes" class="mt-0.5 whitespace-pre-line text-[11px] text-gray-500">{{ h.notes }}</p>
							<!-- Fotonya ikut di baris riwayat, bukan disembunyikan di balik ketukan:
							     gambar tumpukan itulah yang dicocokkan orang berikutnya, dan riwayat
							     berisi kalimat telanjang membuat setiap baris harus dibuka dulu untuk
							     tahu apakah ada yang bisa dilihat. -->
							<div v-if="h.photos?.length" class="mt-1.5 flex gap-1.5">
								<img
									v-for="(url, k) in h.photos"
									:key="k"
									:src="photoSrc(url)"
									class="h-14 w-14 rounded-lg border border-gray-200 object-cover"
									@click="openLightbox(h.photos.map(photoSrc), k)"
								/>
							</div>
						</div>
					</li>
				</ol>
			</section>

			<div class="oak-footer">
				<router-link
					:to="{ path: '/tank-position', query: { c: container } }"
					class="oak-btn oak-btn-primary min-h-[52px] w-full text-base"
				>
					{{ labels.posHistUpdate }}
				</router-link>
			</div>
		</template>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import { cachedResource } from "@/data/cache"
import { photoSrc } from "@/data/send"
import { labels } from "@/utils/labels"
import { fmtDateTime } from "@/utils/surveyStatus"
import { openLightbox } from "@/utils/lightbox"
import Icon from "@/components/Icon.vue"

const route = useRoute()
const router = useRouter()
const container = computed(() => String(route.params.container || ""))

const res = cachedResource({
	url: "container_depot.ess.container_position.tank_position",
	method: "GET",
	makeParams: () => ({ container: container.value }),
	auto: true,
})
const tank = computed(() => res.data || null)
const history = computed(() => tank.value?.history || [])

const headLine = computed(() =>
	[tank.value?.principal, tank.value?.depot ? `depot ${tank.value.depot}` : null]
		.filter(Boolean)
		.join(" · ")
)

function fill(tpl, vars) {
	return Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), tpl)
}
function metaLine(h) {
	const parts = [fmtDateTime(h.recorded_on)]
	if (h.recorded_by) parts.push(h.recorded_by)
	if (h.photos?.length) parts.push(fill(labels.posHistPhotos, { n: h.photos.length }))
	return parts.join(" · ")
}

function goBack() {
	if (window.history.length > 1) router.back()
	else router.push("/tank-position")
}
</script>
