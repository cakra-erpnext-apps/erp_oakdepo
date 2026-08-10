<template>
	<div v-if="show" class="space-y-2" role="status" :aria-label="labels.loading">
		<div v-for="n in rows" :key="n" class="oak-card flex items-center gap-3 p-4">
			<div class="oak-skeleton h-11 w-11 shrink-0 rounded-xl"></div>
			<div class="min-w-0 flex-1 space-y-2">
				<div class="oak-skeleton h-4 w-2/5"></div>
				<div class="oak-skeleton h-3 w-3/4"></div>
				<div class="oak-skeleton h-2.5 w-1/3"></div>
			</div>
			<div v-if="action" class="oak-skeleton h-7 w-14 shrink-0 rounded-lg"></div>
		</div>
	</div>
</template>

<script setup>
// The worklist placeholder for the order queues (Cleaning, M&R, Uji Periodik), whose rows all
// share one shape: tile, three lines of text, an action on the right.
//
// Deliberately mimics that shape rather than being a generic grey box. A placeholder the same
// size as what replaces it means the page does not jump when the data lands, and the operator
// can already see how many rows are coming — which a centred spinner tells them nothing about.
import { labels } from "@/utils/labels"
import { useDeferredShow } from "@/utils/deferredShow"

defineProps({
	rows: { type: Number, default: 4 },
	// Queues where every row carries a "Mulai" button; leave off where they do not.
	action: { type: Boolean, default: true },
})

// Held back briefly so a fast response never flashes a placeholder — see the util.
const show = useDeferredShow()
</script>
