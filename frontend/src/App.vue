<template>
	<!-- Opened from a phone browser instead of the home screen: nothing else renders, and
	     there is no way past it. On iOS this is not a preference — Web Push is only
	     delivered to an installed PWA, so a job notification would never arrive in Safari. -->
	<InstallGate v-if="needsInstall" />

	<div v-else class="flex min-h-screen flex-col bg-gray-50 text-gray-900">
		<header
			ref="appHeader"
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
			<!-- One banner for the whole app rather than a badge per list. Every screen is
			     affected by the same thing, and an operator needs the explanation once. -->
			<p
				v-if="session.isLoggedIn && !link.online"
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
import { onMounted, onBeforeUnmount, ref } from "vue"
import { session } from "@/data/session"
import { labels } from "@/utils/labels"
import { link } from "@/data/link"
import { clearBrowserVisits, mustInstall } from "@/utils/install"
import Icon from "@/components/Icon.vue"
import InstallGate from "@/components/InstallGate.vue"
import BottomNav from "@/components/BottomNav.vue"
import NotificationBell from "@/components/NotificationBell.vue"
import ToastHost from "@/components/ToastHost.vue"
import LightboxHost from "@/components/LightboxHost.vue"
import ConfirmHost from "@/components/ConfirmHost.vue"
import emblem from "@/assets/oak-emblem.png"

// Read once at boot, and never again: the only way out of this screen is relaunching
// from the home screen, which is a fresh load anyway. Nothing in the session can clear it.
const needsInstall = mustInstall()

// Running standalone means the ask finally worked. Drop the browser-visit tally so a
// reinstall later starts from a clean slate rather than resuming an old grudge.
if (!needsInstall) clearBrowserVisits()

// A page that wants a floating sub-header of its own (the EIR form) has to stick BELOW this
// bar, and how tall it is depends on the notch and on whether the offline banner is up. So
// it is measured and published as --oak-header-h; `.oak-subheader` in main.css reads it.
const appHeader = ref(null)
let headerWatcher = null
onMounted(() => {
	if (!appHeader.value || typeof ResizeObserver === "undefined") return
	// Border box, not contentRect: the bar's notch allowance is PADDING (pt-safe-top), and
	// a content-box measurement would park everything below it too high on a notched phone.
	headerWatcher = new ResizeObserver(([entry]) => {
		const h = entry.borderBoxSize?.[0]?.blockSize ?? entry.target.getBoundingClientRect().height
		document.documentElement.style.setProperty("--oak-header-h", `${Math.round(h)}px`)
	})
	headerWatcher.observe(appHeader.value)
})
onBeforeUnmount(() => headerWatcher?.disconnect())
</script>
