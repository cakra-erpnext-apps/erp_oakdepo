<template>
	<div class="flex min-h-screen flex-col items-center justify-center gap-5 bg-gray-50 px-6 py-10">
		<div class="oak-card relative w-full max-w-md overflow-hidden animate-slide-up">
			<div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-500 to-leaf-500"></div>
			<div class="p-6 text-center">
				<img :src="emblem" alt="OAK" class="mx-auto h-16 w-16" />
				<p class="mt-3 text-lg font-extrabold tracking-tight text-gray-900">
					{{ labels.installTitle }}
				</p>
				<p class="mt-1.5 text-sm leading-relaxed text-gray-500">{{ labels.installBody }}</p>

				<!-- Android/Chrome hands us a real install prompt; everything else has to be
				     talked through it by hand. -->
				<button v-if="deferred" class="oak-btn oak-btn-primary mt-5 w-full" @click="install">
					<Icon name="download" :size="16" />
					{{ labels.installBtn }}
				</button>

				<div v-else class="mt-5 space-y-2 text-left">
					<p v-if="iosNonSafari" class="oak-card bg-amber-50 p-3 text-sm font-medium text-amber-800">
						{{ labels.installIosSafari }}
					</p>
					<template v-else>
						<p class="oak-eyebrow">{{ isIos ? labels.installIosTitle : labels.installAndroidTitle }}</p>
						<ol class="space-y-2">
							<li v-for="(s, i) in steps" :key="i" class="flex gap-2.5 text-sm text-gray-600">
								<span
									class="oak-icon-tile h-6 w-6 shrink-0 bg-brand-50 text-xs font-bold text-brand-700"
								>
									{{ i + 1 }}
								</span>
								<span class="pt-0.5">{{ s }}</span>
							</li>
						</ol>
					</template>
				</div>
			</div>
		</div>

		<!-- Deliberately quiet, and deliberately present. A hard block is the point, but a
		     yard worker on a browser that simply cannot install (Chrome on iOS, an old
		     Android WebView) must not be locked out of their shift. Session-scoped, so the
		     install ask returns next time the app is opened. -->
		<button type="button" class="text-sm text-gray-400 underline underline-offset-2" @click="skip">
			{{ labels.installSkip }}
		</button>
		<p class="-mt-3 text-center text-xs text-gray-400">{{ labels.installSkipHint }}</p>
	</div>
</template>

<script setup>
import { ref } from "vue"
import { labels } from "@/utils/labels"
import { isIos, markInstallSkipped } from "@/utils/install"
import Icon from "@/components/Icon.vue"
import emblem from "@/assets/oak-emblem.png"

const emit = defineEmits(["skip"])

// Chrome fires this before showing its own mini-infobar; holding on to the event is the
// only way to trigger the install sheet from our own button later.
const deferred = ref(null)
window.addEventListener("beforeinstallprompt", (e) => {
	e.preventDefault()
	deferred.value = e
})

const ua = navigator.userAgent
const iosNonSafari = isIos() && /CriOS|FxiOS|EdgiOS|OPiOS/.test(ua)

const steps = isIos()
	? [labels.installIosStep1, labels.installIosStep2, labels.installIosStep3]
	: [labels.installAndroidStep1, labels.installAndroidStep2]

async function install() {
	const e = deferred.value
	if (!e) return
	deferred.value = null
	e.prompt()
	await e.userChoice
	// No branch on the outcome: an accepted install reloads into standalone on its own,
	// and a dismissed one should leave this screen up rather than wave the user through.
}

function skip() {
	markInstallSkipped()
	emit("skip")
}
</script>
