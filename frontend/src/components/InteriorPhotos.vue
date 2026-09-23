<template>
	<!-- Foto interior dari survey tank, masing-masing dengan deskripsinya. Hanya tampil. -->
	<div v-if="photos.length" class="space-y-1.5">
		<p class="text-xs text-gray-500">{{ labels.tankInteriorPhotos }}</p>
		<div class="grid grid-cols-3 gap-2">
			<button
				v-for="(p, i) in photos"
				:key="i"
				type="button"
				class="oak-press min-w-0 text-left"
				@click="openLightbox(photos.map((x) => ({ src: photoSrc(x.photo), caption: x.caption })), i)"
			>
				<img :src="photoSrc(p.photo)" class="aspect-square w-full rounded-lg border border-gray-200 object-cover" />
				<span v-if="p.caption" :title="p.caption" class="mt-0.5 block truncate text-[11px] text-gray-600">
					{{ p.caption }}
				</span>
			</button>
		</div>
	</div>
</template>

<script setup>
import { labels } from "@/utils/labels"
import { openLightbox } from "@/utils/lightbox"
import { photoSrc } from "@/data/send"

defineProps({ photos: { type: Array, default: () => [] } })
</script>
