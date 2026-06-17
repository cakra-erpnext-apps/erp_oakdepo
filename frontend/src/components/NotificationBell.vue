<template>
	<div class="flex items-center">
		<button
			class="relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-500 transition hover:bg-gray-100"
			:aria-label="labels.notifications"
			@click="toggle"
		>
			<Icon name="bell" :size="20" />
			<span
				v-if="unread"
				class="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-brand-600 px-1 text-[10px] font-bold leading-none text-white"
			>
				{{ unread > 9 ? "9+" : unread }}
			</span>
		</button>

		<template v-if="open">
			<div class="fixed inset-0 z-40" @click="open = false"></div>
			<div
				class="fixed right-2 z-50 flex max-h-[70vh] w-[min(22rem,calc(100vw-1rem))] flex-col overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-soft animate-slide-up md:right-4"
				style="top: calc(env(safe-area-inset-top) + 3.5rem)"
			>
				<div class="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
					<p class="font-bold text-gray-900">{{ labels.notifications }}</p>
					<button
						v-if="unread"
						class="text-xs font-semibold text-brand-600 hover:text-brand-700"
						@click="markAll"
					>
						{{ labels.notifMarkAll }}
					</button>
				</div>
				<div class="flex-1 overflow-y-auto">
					<p v-if="!items.length" class="px-4 py-10 text-center text-sm text-gray-400">
						{{ labels.notifEmpty }}
					</p>
					<ul v-else class="divide-y divide-gray-100">
						<li
							v-for="n in items"
							:key="n.name"
							class="flex cursor-pointer gap-3 px-4 py-3 transition hover:bg-gray-50"
							:class="n.read ? '' : 'bg-brand-50/50'"
							@click="markOne(n)"
						>
							<span
								class="mt-1.5 h-2 w-2 shrink-0 rounded-full"
								:class="n.read ? 'bg-transparent' : 'bg-brand-500'"
							></span>
							<div class="min-w-0 flex-1">
								<p class="break-words text-sm text-gray-800" v-html="n.subject"></p>
								<p class="mt-0.5 text-xs text-gray-400">{{ fromNow(n.creation) }}</p>
							</div>
						</li>
					</ul>
				</div>
				<!-- Footer: toggle the toast/notification chime -->
				<button
					class="flex items-center justify-between gap-2 border-t border-gray-100 px-4 py-2.5 text-sm text-gray-600 transition hover:bg-gray-50"
					@click="toggleSound"
				>
					<span class="flex items-center gap-2">
						<Icon :name="soundOn ? 'volume-2' : 'volume-x'" :size="16" />
						{{ labels.notifSound }}
					</span>
					<span
						class="inline-flex h-5 w-9 items-center rounded-full px-0.5 transition"
						:class="soundOn ? 'bg-brand-600' : 'bg-gray-300'"
					>
						<span
							class="h-4 w-4 rounded-full bg-white shadow transition"
							:class="soundOn ? 'translate-x-4' : 'translate-x-0'"
						></span>
					</span>
				</button>
			</div>
		</template>
	</div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue"
import { createResource } from "frappe-ui"
import dayjs from "dayjs"
import relativeTime from "dayjs/plugin/relativeTime"
import "dayjs/locale/id"
import Icon from "@/components/Icon.vue"
import { labels } from "@/utils/labels"
import { toast, toastSoundOn, setToastSound } from "@/utils/toast"

dayjs.extend(relativeTime)
dayjs.locale("id")

const open = ref(false)
const soundOn = ref(toastSoundOn())
function toggleSound() {
	setToastSound(!soundOn.value)
	soundOn.value = toastSoundOn()
	if (soundOn.value) toast.info(labels.notifSoundOn)
}
const items = ref([])
const unread = ref(0)
let timer = null

const listRes = createResource({
	url: "container_depot.ess.notifications.list_notifications",
	method: "GET",
	onSuccess(data) {
		items.value = data.items || []
		unread.value = data.unread || 0
	},
})
const markReadRes = createResource({ url: "container_depot.ess.notifications.mark_read", method: "POST" })
const markAllRes = createResource({ url: "container_depot.ess.notifications.mark_all_read", method: "POST" })

function load() {
	listRes.submit({ limit: 20 })
}

function toggle() {
	open.value = !open.value
	if (open.value) load()
}

// Optimistic: flip locally, then persist (best-effort).
function markOne(n) {
	if (!n.read) {
		n.read = 1
		unread.value = Math.max(0, unread.value - 1)
		markReadRes.submit({ name: n.name })
	}
}

function markAll() {
	items.value.forEach((n) => (n.read = 1))
	unread.value = 0
	markAllRes.submit({})
}

function fromNow(t) {
	return t ? dayjs(t).fromNow() : ""
}

onMounted(() => {
	load()
	timer = setInterval(load, 60000) // refresh the badge while the app is open
})
onBeforeUnmount(() => {
	if (timer) clearInterval(timer)
})
</script>
