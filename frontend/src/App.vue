<template>
	<div class="min-h-screen flex flex-col bg-gray-50 text-gray-900">
		<header
			class="sticky top-0 z-10 flex items-center justify-between gap-3 border-b bg-white px-4 py-3 pt-safe-top"
		>
			<router-link to="/" class="flex items-center gap-2 font-semibold">
				<img :src="logoUrl" alt="" class="h-6 w-6 rounded" />
				<span>{{ labels.appName }}</span>
			</router-link>
			<button
				v-if="session.isLoggedIn"
				class="text-sm text-gray-500 hover:text-gray-900"
				@click="session.logout()"
			>
				{{ labels.logout }}
			</button>
		</header>

		<main class="flex-1 px-4 py-4 pb-safe-bottom">
			<router-view v-slot="{ Component }">
				<component :is="Component" />
			</router-view>
		</main>
	</div>
</template>

<script setup>
import { session } from "@/data/session"
import { labels } from "@/utils/labels"

// Reference the public/ icon via the build base so Vite doesn't try to resolve
// the absolute runtime URL as a source asset at build time.
const logoUrl = `${import.meta.env.BASE_URL}icons/icon-192.png`
</script>
