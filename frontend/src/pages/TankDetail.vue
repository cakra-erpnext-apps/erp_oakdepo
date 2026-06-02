<template>
	<div class="mx-auto w-full max-w-lg">
		<h1 class="text-lg font-semibold">{{ labels.detail }}</h1>
		<p class="mt-2 text-sm text-gray-500">{{ name }}</p>
	</div>
</template>

<script setup>
// Placeholder — implemented in Feature F1.
import { labels } from "@/utils/labels"

defineProps({ name: { type: String, default: "" } })
</script>
