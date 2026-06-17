<template>
	<div class="flex min-h-screen flex-col bg-gray-50 text-gray-900">
		<header
			class="sticky top-0 z-20 border-b border-gray-200/80 bg-white/90 pt-safe-top shadow-header backdrop-blur"
		>
			<div class="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-2.5">
				<router-link to="/" class="flex items-center gap-2.5">
					<img :src="emblem" alt="OAK" class="h-9 w-9" />
					<span class="text-[15px] font-extrabold leading-none tracking-tight text-gray-900">
						Depot <span class="text-brand-600">OAK</span>
					</span>
				</router-link>
				<div v-if="session.isLoggedIn" class="flex items-center gap-1">
					<NotificationBell />
					<button
						class="oak-btn oak-btn-ghost -mr-1.5 h-9 gap-1.5 px-2.5 text-xs text-gray-500"
						@click="session.logout()"
					>
						<Icon name="log-out" :size="16" />
						<span>{{ labels.logout }}</span>
					</button>
				</div>
			</div>
		</header>

		<main class="flex-1 px-4 py-4 pb-28">
			<router-view v-slot="{ Component }">
				<transition name="page" mode="out-in">
					<component :is="Component" />
				</transition>
			</router-view>
		</main>

		<BottomNav v-if="session.isLoggedIn" />
		<ToastHost />
	</div>
</template>

<script setup>
import { session } from "@/data/session"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import BottomNav from "@/components/BottomNav.vue"
import NotificationBell from "@/components/NotificationBell.vue"
import ToastHost from "@/components/ToastHost.vue"
import emblem from "@/assets/oak-emblem.png"
</script>
