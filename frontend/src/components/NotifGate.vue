<template>
	<!-- Overlay, not a route: every screen is equally unusable without notifications, and a
	     guard per page would be the same check written ten times. Sits above the header and
	     the bottom nav on purpose — there is no way past it but turning notifications on. -->
	<div
		v-if="show"
		class="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 overflow-y-auto oak-yard px-6 py-10"
	>
		<div class="oak-card relative w-full max-w-md overflow-hidden animate-slide-up">
			<div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-500 to-leaf-500"></div>
			<div class="p-6 text-center">
				<span class="oak-icon-tile mx-auto h-14 w-14 bg-brand-50 text-brand-700">
					<Icon :name="denied ? 'bell-off' : 'bell'" :size="26" />
				</span>

				<!-- Permission already refused. The browser will not prompt again, so the only
				     useful thing on this screen is where the switch actually lives. -->
				<template v-if="denied">
					<p class="mt-3 text-lg font-extrabold tracking-tight text-gray-900">
						{{ labels.pushGateDeniedTitle }}
					</p>
					<p class="mt-1.5 text-sm leading-relaxed text-gray-500">{{ labels.pushGateDeniedBody }}</p>
					<ol class="mt-5 space-y-2 text-left">
						<li v-for="(s, i) in steps" :key="i" class="flex gap-2.5 text-sm text-gray-600">
							<span class="oak-icon-tile h-6 w-6 shrink-0 bg-brand-50 text-xs font-bold text-brand-700">
								{{ i + 1 }}
							</span>
							<span class="pt-0.5">{{ s }}</span>
						</li>
					</ol>
					<button class="oak-btn oak-btn-primary mt-5 w-full" :disabled="push.busy" @click="recheck">
						<Icon name="refresh-cw" :size="16" />
						{{ labels.pushGateRecheck }}
					</button>
				</template>

				<template v-else>
					<p class="mt-3 text-lg font-extrabold tracking-tight text-gray-900">
						{{ labels.pushGateTitle }}
					</p>
					<p class="mt-1.5 text-sm leading-relaxed text-gray-500">{{ labels.pushGateBody }}</p>
					<button class="oak-btn oak-btn-primary mt-5 w-full" :disabled="push.busy" @click="enable">
						<Icon name="bell" :size="16" />
						{{ push.busy ? labels.pushWorking : labels.pushGateBtn }}
					</button>
					<p class="mt-2 text-xs text-gray-400">{{ labels.pushGateAllow }}</p>
				</template>

				<p v-if="note" class="mt-3 text-xs font-medium text-amber-700">{{ note }}</p>

				<!-- Escape hatch. Always here, because the states it exists for (a browser that
				     cannot subscribe, a deployment without the worker header) are not always
				     reported as an error — some of them just never succeed. Deliberately the
				     quietest thing on the screen, and it only buys a day. -->
				<button
					class="oak-btn oak-btn-ghost mt-3 w-full text-gray-500"
					:disabled="push.busy"
					@click="skip"
				>
					{{ labels.pushGateSkip }}
				</button>
				<p class="mt-1 text-xs leading-relaxed text-gray-400">{{ labels.pushGateSkipHint }}</p>
			</div>
		</div>

		<details class="w-full max-w-md">
			<summary
				class="cursor-pointer list-none text-center text-sm text-gray-400 underline underline-offset-2 [&::-webkit-details-marker]:hidden"
			>
				{{ labels.pushGateWhy }}
			</summary>
			<p class="mt-2 text-center text-xs leading-relaxed text-gray-500">{{ labels.pushGateWhyBody }}</p>
		</details>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { GATE_SNOOZE_MS, enablePush, push, pushGateNeeded, snoozePushGate } from "@/data/push"
import { isIos } from "@/utils/install"
import { labels } from "@/utils/labels"
import Icon from "@/components/Icon.vue"

// Nothing renders until the check answers: the gate asks the server whether push is even
// configured, and flashing a full-screen block for the moment that takes would make a
// correctly-configured handset look broken on every launch.
const show = ref(false)

const denied = computed(() => push.permission === "denied")
const steps = isIos()
	? [labels.pushGateIosStep1, labels.pushGateIosStep2]
	: [labels.pushGateAndroidStep1, labels.pushGateAndroidStep2]

// "denied" already owns the whole screen above, so it is not repeated here.
const note = computed(() => {
	if (push.error === "sw-timeout") return labels.pushSwTimeout
	if (push.error && push.error !== "denied") return labels.pushFailed
	return ""
})

// Re-asked every time the app comes back to the foreground, not once at boot. One check
// per load would let an operator who turns notifications off mid-shift (or whose
// subscription is dropped server-side after a reinstall) keep working silently until the
// next cold start — which on a handset that never gets closed is never.
async function check() {
	if (push.busy) return // mid-prompt; the enable flow sets the state itself
	show.value = await pushGateNeeded()
}

function onVisible() {
	if (document.visibilityState === "visible") check()
}

// The foreground check alone would not be enough here: a handset left on one screen for
// the whole snooze never fires a visibility event, and the ask would simply never come
// back. So the return is scheduled the moment the operator skips.
let snoozeTimer = null

function skip() {
	snoozePushGate()
	show.value = false
	clearTimeout(snoozeTimer)
	snoozeTimer = setTimeout(check, GATE_SNOOZE_MS)
}

onMounted(() => {
	check()
	document.addEventListener("visibilitychange", onVisible)
	window.addEventListener("focus", onVisible)
})

onBeforeUnmount(() => {
	clearTimeout(snoozeTimer)
	document.removeEventListener("visibilitychange", onVisible)
	window.removeEventListener("focus", onVisible)
})

async function enable() {
	if (await enablePush()) show.value = false
}

// Came back from the OS settings. Re-read rather than re-prompt: with permission now
// granted, subscribing needs no gesture of its own.
async function recheck() {
	if (Notification.permission === "granted") {
		await enable()
		return
	}
	await check()
}
</script>
