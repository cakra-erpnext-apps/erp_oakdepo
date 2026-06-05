<template>
	<span
		class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
		:class="statusColors[bucket] || 'bg-gray-100 text-gray-700'"
	>
		{{ statusLabel(bucket) }}
	</span>
</template>

<script setup>
import { statusColors, statusLabel } from "@/utils/labels"

defineProps({
	bucket: { type: String, default: "" },
})
</script>
