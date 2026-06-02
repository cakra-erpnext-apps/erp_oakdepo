<template>
	<div class="mx-auto w-full max-w-lg space-y-4">
		<section class="rounded-lg border bg-white p-4">
			<p class="text-sm text-gray-500">{{ labels.loggedInAs }}</p>
			<p class="text-lg font-semibold">
				{{ displayUser }}
			</p>
		</section>

		<router-link
			to="/tanks"
			class="block rounded-lg border bg-white p-4 hover:bg-gray-50"
		>
			<p class="font-medium">{{ labels.inventory }}</p>
			<p class="text-sm text-gray-500">
				Inventaris &amp; status tank langsung
			</p>
		</router-link>
	</div>
</template>

<script setup>
import { computed, onMounted } from "vue"
import { session } from "@/data/session"
import { userResource } from "@/data/user"
import { labels } from "@/utils/labels"

onMounted(() => {
	// Confirm the logged-in user server-side (PRD Phase 0 deliverable).
	if (session.isLoggedIn && !userResource.data) userResource.reload()
})

const displayUser = computed(() => userResource.data || session.user || "—")
</script>
