<template>
	<div v-if="show" class="space-y-4" role="status" :aria-label="labels.loading">
		<!-- Tank header: the 2-column spec grid every detail screen opens with. -->
		<section class="oak-card space-y-3 p-4">
			<div class="oak-skeleton h-3 w-24"></div>
			<div class="grid grid-cols-2 gap-x-3 gap-y-3">
				<div v-for="n in cells" :key="n" class="space-y-1.5">
					<div class="oak-skeleton h-2.5 w-16"></div>
					<div class="oak-skeleton h-3.5 w-4/5"></div>
				</div>
			</div>
		</section>

		<!-- The body sections below it. -->
		<section v-for="n in sections" :key="`s${n}`" class="oak-card space-y-3 p-4">
			<div class="oak-skeleton h-3 w-28"></div>
			<div class="oak-skeleton h-3 w-full"></div>
			<div class="oak-skeleton h-3 w-5/6"></div>
		</section>

		<div class="oak-skeleton h-12 w-full rounded-xl"></div>
	</div>
</template>

<script setup>
// Placeholder for a detail/form screen while its record loads.
//
// This one exists because the alternative was nothing at all: the detail views render behind
// `v-if="order"`, so tapping a tank left the previous screen sitting there unchanged. Not a
// blank page — worse. It read as "the tap did not register", and on a slow handset that means
// the operator taps again, and again.
import { ref } from "vue"

import { labels } from "@/utils/labels"
import { useDeferredShow } from "@/utils/deferredShow"

const props = defineProps({
	cells: { type: Number, default: 6 },   // spec fields in the header grid
	sections: { type: Number, default: 2 },
	// Default 0 — no delay — because this placeholder normally REPLACES a screen that has
	// just disappeared (worklist → detail). Holding it back there buys a blank page, which is
	// the very thing it was added to remove, and a same-shaped placeholder swapping to content
	// does not read as a flicker even when it is quick.
	//
	// Pass a delay where it appears BELOW content that is still on screen — the gate lookup
	// panel — because there it does have a blank space to flash into.
	delay: { type: Number, default: 0 },
})

const show = props.delay ? useDeferredShow(props.delay) : ref(true)
</script>
