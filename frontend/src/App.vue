<template>
	<!-- Opened from a phone browser instead of the home screen: nothing else renders until
	     it is installed. On iOS that is not a preference — Web Push is only delivered to an
	     installed PWA, so a job notification would never arrive from Safari. -->
	<InstallGate v-if="needsInstall" @skip="needsInstall = false" />

	<div v-else class="flex min-h-screen flex-col bg-gray-50 text-gray-900">
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
					<OutboxBadge />
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
			<!-- One banner for the whole app rather than a badge per list. Every screen is
			     affected by the same thing, and an operator needs the explanation once. -->
			<p
				v-if="session.isLoggedIn && !outbox.online"
				class="border-t border-amber-200 bg-amber-50 px-4 py-1.5 text-center text-[11px] leading-snug text-amber-800"
			>
				{{ labels.offlineBanner }}
			</p>
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
		<LightboxHost />
		<ConfirmHost />
	</div>
</template>

<script setup>
import { ref } from "vue"
import { session } from "@/data/session"
import { labels } from "@/utils/labels"
import { outbox } from "@/data/outbox"
import { mustInstall } from "@/utils/install"
import Icon from "@/components/Icon.vue"
import InstallGate from "@/components/InstallGate.vue"
import BottomNav from "@/components/BottomNav.vue"
import NotificationBell from "@/components/NotificationBell.vue"
import OutboxBadge from "@/components/OutboxBadge.vue"
import ToastHost from "@/components/ToastHost.vue"
import LightboxHost from "@/components/LightboxHost.vue"
import ConfirmHost from "@/components/ConfirmHost.vue"
import emblem from "@/assets/oak-emblem.png"

// Read once at boot rather than as a computed: an install completes by relaunching the
// app standalone, so re-evaluating mid-session would only ever flip on the escape hatch.
const needsInstall = ref(mustInstall())
</script>
