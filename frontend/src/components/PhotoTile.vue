<template>
	<div class="tile relative shrink-0 overflow-hidden rounded-lg border" :class="[tile, frame]">
		<!-- The picture the operator just took, in the grid, from the first frame. -->
		<img :src="item.preview" alt="" class="h-full w-full object-cover" :class="failed ? 'opacity-40' : 'opacity-60'" />

		<div class="absolute inset-0 flex flex-col items-center justify-center gap-1">
			<span
				class="flex h-7 w-7 items-center justify-center rounded-full text-white shadow"
				:class="failed ? 'bg-red-500' : 'bg-gray-900/70'"
			>
				<Icon v-if="failed" name="alert-triangle" :size="14" />
				<Icon v-else name="loader" :size="14" class="animate-spin" />
			</span>
			<span
				class="rounded px-1 text-[9px] font-semibold leading-none"
				:class="failed ? 'bg-red-500 text-white' : 'bg-gray-900/70 text-white'"
			>
				{{ failed ? labels.photoMarkFailed : labels.photoMarkUploading }}
			</span>
		</div>

		<!-- Indeterminate sweep along the bottom edge. There is no real progress to report
		     (the upload is one request), so it says "still moving" rather than pretending to
		     a percentage — and a bar that moves is the difference between a slow upload and
		     a dead app on a 3G yard. -->
		<span v-if="!failed" class="sweep absolute inset-x-0 bottom-0 h-[3px] overflow-hidden bg-black/20">
			<span class="block h-full w-1/3 bg-brand-400"></span>
		</span>
	</div>
</template>

<script setup>
// A photo mid-flight, shown as itself.
//
// Two states, and only ONE of them means a photo is in danger:
//
// * `uploading` — going up now. Dimmed, spinner, moving bar.
// * `failed`    — it went nowhere and has to be retaken. Rare: an upload that cannot REACH
//   the server is not a failure at all, `uploadPhoto` parks it on the handset and the
//   document carries it on Kirim (the amber clock in PhotoMark). This is for the case where
//   even parking it failed, which is the only time the operator has to act.
//
// `tile` carries the size classes so it matches whichever grid it stands in.
import { computed } from "vue"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const props = defineProps({
	item: { type: Object, required: true }, // from utils/photoQueue
	tile: { type: String, default: "h-20 w-20" },
})
const failed = computed(() => props.item.state === "failed")
const frame = computed(() =>
	failed.value ? "border-red-300 bg-red-50" : "border-gray-300 bg-gray-100"
)
</script>

<style scoped>
/* Arriving is the answer to the shutter, so it must not be subtle. */
.tile {
	animation: tile-in 0.18s ease-out;
}
@keyframes tile-in {
	from {
		opacity: 0;
		transform: scale(0.9);
	}
}
.sweep > span {
	animation: sweep 1.1s ease-in-out infinite;
}
@keyframes sweep {
	0% {
		transform: translateX(-100%);
	}
	100% {
		transform: translateX(300%);
	}
}
@media (prefers-reduced-motion: reduce) {
	.tile,
	.sweep > span {
		animation: none;
	}
}
</style>
