<template>
	<span
		class="mark absolute bottom-1 right-1 flex h-[18px] w-[18px] items-center justify-center rounded-full text-white shadow ring-1 ring-white/60"
		:class="parked ? 'bg-amber-500' : 'bg-leaf-600'"
		:title="parked ? labels.photoMarkParked : labels.photoMarkSent"
	>
		<Icon :name="parked ? 'clock' : 'check'" :size="11" :stroke="3" />
	</span>
</template>

<script setup>
// Did this photo actually get out of my hand? Two answers, drawn on the picture itself:
// green tick = it is on the server, amber clock = it is still only on this handset and
// leaves with the document on Kirim (`uploadPhoto` parks rather than fails, so a photo is
// never lost — but "safe here" and "safe there" are different things and the operator is
// entitled to know which one they are looking at).
//
// The toast that says the same thing is gone two seconds later and says it about "a photo",
// not about THIS photo. The badge is per picture and stays.
//
// Needs a positioned parent — every thumbnail wrapper that uses this is `relative`.
import { computed } from "vue"
import { isLocalRef } from "@/data/send"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

const props = defineProps({ photo: { type: String, default: "" } })
const parked = computed(() => isLocalRef(props.photo))
</script>

<style scoped>
/* The tick pops in where the spinner just was — the same square, one beat later. That beat
   is the whole message: it moved, and it arrived. */
.mark {
	animation: mark-in 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes mark-in {
	from {
		opacity: 0;
		transform: scale(0.4);
	}
}
@media (prefers-reduced-motion: reduce) {
	.mark {
		animation: none;
	}
}
</style>
