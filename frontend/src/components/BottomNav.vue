<template>
	<nav
		class="fixed inset-x-0 bottom-0 z-30 border-t border-gray-200 bg-white/95 pb-safe-bottom backdrop-blur-md"
	>
		<div class="mx-auto flex max-w-2xl items-stretch justify-around px-1">
			<router-link
				v-for="t in tabs"
				:key="t.to"
				:to="t.to"
				class="group flex flex-1 flex-col items-center gap-1 py-1.5 transition-colors"
				:class="isActive(t) ? 'text-brand-600' : 'text-gray-400 hover:text-gray-600'"
			>
				<span
					class="oak-icon-tile h-8 w-10 transition-colors"
					:class="isActive(t) ? 'bg-brand-50' : 'bg-transparent'"
				>
					<Icon :name="t.icon" :size="20" :stroke="isActive(t) ? 2.4 : 2" />
				</span>
				<span class="text-center text-[11px] font-semibold leading-tight">{{ t.label }}</span>
			</router-link>
		</div>
	</nav>
</template>

<script setup>
import { useRoute } from "vue-router"
import Icon from "@/components/Icon.vue"
import { labels } from "@/utils/labels"

const route = useRoute()

const tabs = [
	{ to: "/", icon: "home", label: labels.navHome },
	{ to: "/gate", icon: "log-in", label: labels.navGate },
	{ to: "/eir", icon: "clipboard", label: labels.navEir },
	{ to: "/cleaning", icon: "droplet", label: labels.navCleaning },
	{ to: "/mr", icon: "tool", label: labels.navMr },
	{ to: "/monitor", icon: "grid", label: labels.navMonitor || labels.monitorTitle },
]

function isActive(t) {
	const p = route.path
	if (t.to === "/") return p === "/"
	if (t.to === "/eir") return p === "/eir" // not /eir/history
	return p === t.to || p.startsWith(t.to + "/")
}
</script>
