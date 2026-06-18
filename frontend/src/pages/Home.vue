<template>
	<div class="mx-auto w-full max-w-lg space-y-4 md:max-w-2xl">
		<!-- Greeting hero -->
		<section class="oak-card relative overflow-hidden animate-slide-up">
			<div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-500 to-leaf-500"></div>
			<img
				:src="emblem"
				alt=""
				class="pointer-events-none absolute -right-6 -top-4 h-32 w-32 opacity-[0.06]"
			/>
			<div class="relative z-10 p-5">
				<p class="oak-eyebrow">{{ labels.greeting }} 👋</p>
				<p class="mt-1 truncate text-xl font-extrabold tracking-tight text-gray-900">
					{{ displayUser }}
				</p>
				<p class="mt-0.5 text-sm text-gray-500">{{ labels.homeHint }}</p>
			</div>
		</section>

		<!-- Menu -->
		<div class="grid gap-3 sm:grid-cols-2">
			<router-link
				v-for="(m, i) in menu"
				:key="m.to"
				:to="m.to"
				class="oak-card oak-press flex animate-slide-up items-center gap-4 p-4"
				:class="m.wide ? 'sm:col-span-2' : ''"
				:style="{ animationDelay: 60 + i * 50 + 'ms' }"
			>
				<span class="oak-icon-tile h-12 w-12" :class="m.tile">
					<Icon :name="m.icon" :size="24" />
				</span>
				<div class="min-w-0 flex-1">
					<p class="font-bold text-gray-900">{{ m.title }}</p>
					<p class="mt-0.5 text-sm text-gray-500">{{ m.desc }}</p>
				</div>
				<Icon name="chevron-right" :size="20" class="text-gray-300" />
			</router-link>
		</div>
	</div>
</template>

<script setup>
import { computed, onMounted } from "vue"
import { session } from "@/data/session"
import { userResource } from "@/data/user"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"
import emblem from "@/assets/oak-emblem.png"

onMounted(() => {
	// Confirm the logged-in user server-side (PRD Phase 0 deliverable).
	if (session.isLoggedIn && !userResource.data) userResource.reload()
})

const displayUser = computed(() => userResource.data || session.user || "—")

const menu = [
	{
		to: "/gate",
		icon: "log-in",
		title: labels.gate,
		desc: labels.gateDesc,
		tile: "bg-brand-50 text-brand-600",
	},
	{
		to: "/eir",
		icon: "clipboard",
		title: labels.eir,
		desc: labels.eirDesc,
		tile: "bg-leaf-50 text-leaf-600",
	},
	{
		to: "/cleaning",
		icon: "droplet",
		title: labels.cleaningTitle,
		desc: labels.cleaningDesc,
		tile: "bg-brand-50 text-brand-600",
	},
	{
		to: "/mr",
		icon: "tool",
		title: labels.mrTitleFull,
		desc: labels.mrDesc,
		tile: "bg-leaf-50 text-leaf-600",
	},
	{
		to: "/storage",
		icon: "layers",
		title: labels.storage,
		desc: labels.storageDesc,
		tile: "bg-leaf-50 text-leaf-600",
	},
	{
		to: "/monitor",
		icon: "grid",
		title: labels.monitorTitle,
		desc: labels.monitorDesc,
		tile: "bg-brand-50 text-brand-600",
	},
	{
		to: "/eir/history",
		icon: "clock",
		title: labels.eirHistoryTitle,
		desc: labels.eirHistoryDesc,
		tile: "bg-gray-100 text-gray-500",
		wide: true,
	},
]
</script>
