<template>
	<div class="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-50 px-6 py-10">
		<!-- Second visit onwards. Deliberately above the card rather than inside a branch:
		     whatever is blocking this person, the fact that it has now blocked them twice is
		     the part they have not been told. -->
		<div
			v-if="repeat"
			class="oak-card w-full max-w-md border-amber-200 bg-amber-50 p-4 animate-slide-up"
		>
			<div class="flex gap-3">
				<span class="oak-icon-tile h-9 w-9 shrink-0 bg-amber-100 text-amber-700">
					<Icon name="alert-triangle" :size="18" />
				</span>
				<div class="min-w-0">
					<p class="text-sm font-bold text-amber-900">{{ labels.installRepeatTitle }}</p>
					<p class="mt-1 text-sm leading-relaxed text-amber-800">{{ repeatBody }}</p>
					<p class="mt-2 text-xs font-medium text-amber-700">{{ labels.installRepeatHelp }}</p>
				</div>
			</div>
		</div>

		<div class="oak-card relative w-full max-w-md overflow-hidden animate-slide-up">
			<div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-500 to-leaf-500"></div>
			<div class="p-6 text-center">
				<img :src="emblem" alt="OAK" class="mx-auto h-16 w-16" />

				<!-- 1. Install accepted. Chrome leaves this tab in the browser, so the last
				     step — open it from the home screen — still has to be asked for. -->
				<template v-if="installed">
					<p class="mt-3 text-lg font-extrabold tracking-tight text-gray-900">
						{{ labels.installDoneTitle }}
					</p>
					<p class="mt-1.5 text-sm leading-relaxed text-gray-500">{{ labels.installDoneBody }}</p>
				</template>

				<!-- 2. Chrome offered us a real install prompt. That is proof this browser can
				     install, so it outranks the user-agent guesses below — a webview mis-detected
				     as such would otherwise be told to leave a browser that was working fine. -->
				<template v-else-if="deferred">
					<p class="mt-3 text-lg font-extrabold tracking-tight text-gray-900">
						{{ labels.installTitle }}
					</p>
					<p class="mt-1.5 text-sm leading-relaxed text-gray-500">{{ labels.installBody }}</p>
					<button class="oak-btn oak-btn-primary mt-5 w-full" @click="install">
						<Icon name="download" :size="16" />
						{{ labels.installBtn }}
					</button>
				</template>

				<!-- 3. Inside another app's webview (WhatsApp, Instagram, …). No install is
				     possible here at all, so the only useful instruction is how to leave. -->
				<template v-else-if="inApp">
					<p class="mt-3 text-lg font-extrabold tracking-tight text-gray-900">
						{{ labels.installWebviewTitle }}
					</p>
					<p class="mt-1.5 text-sm leading-relaxed text-gray-500">
						{{ ios ? labels.installWebviewIosBody : labels.installWebviewBody }}
					</p>
					<button class="oak-btn oak-btn-primary mt-5 w-full" @click="copyLink">
						<Icon :name="copied ? 'check' : 'copy'" :size="16" />
						{{ copied ? labels.installCopied : labels.installCopyLink }}
					</button>
					<p class="mt-2 break-all text-[11px] leading-snug text-gray-400">{{ appUrl }}</p>
				</template>

				<!-- 4. Chrome/Firefox/Edge on iOS: WebKit underneath, but Apple gives them no
				     "Add to Home Screen". Only Safari can finish this. -->
				<template v-else-if="iosNonSafari">
					<p class="mt-3 text-lg font-extrabold tracking-tight text-gray-900">
						{{ labels.installTitle }}
					</p>
					<p class="oak-card mt-4 bg-amber-50 p-3 text-left text-sm font-medium text-amber-800">
						{{ labels.installIosSafari }}
					</p>
					<button class="oak-btn oak-btn-primary mt-4 w-full" @click="copyLink">
						<Icon :name="copied ? 'check' : 'copy'" :size="16" />
						{{ copied ? labels.installCopied : labels.installCopyLink }}
					</button>
					<p class="mt-2 break-all text-[11px] leading-snug text-gray-400">{{ appUrl }}</p>
				</template>

				<!-- 5. Safari on iOS, or an Android browser that never offered a prompt: the
				     menu has to be walked through by hand. -->
				<template v-else>
					<p class="mt-3 text-lg font-extrabold tracking-tight text-gray-900">
						{{ labels.installTitle }}
					</p>
					<p class="mt-1.5 text-sm leading-relaxed text-gray-500">{{ labels.installBody }}</p>

					<div class="mt-5 space-y-2 text-left">
						<p class="oak-eyebrow">{{ ios ? labels.installIosTitle : labels.installAndroidTitle }}</p>
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
					</div>
				</template>
			</div>
		</div>

		<!-- No way past this screen, so it owes the operator a reason. Someone who
		     understands why stops hunting for the button that used to let them through. -->
		<details class="w-full max-w-md" :open="repeat">
			<summary
				class="cursor-pointer list-none text-center text-sm text-gray-400 underline underline-offset-2 [&::-webkit-details-marker]:hidden"
			>
				{{ labels.installWhy }}
			</summary>
			<p class="mt-2 text-center text-xs leading-relaxed text-gray-500">{{ labels.installWhyBody }}</p>
		</details>
	</div>
</template>

<script setup>
import { ref } from "vue"
import { labels } from "@/utils/labels"
import { isInAppBrowser, isIos, isIosNonSafari, noteBrowserVisit } from "@/utils/install"
import Icon from "@/components/Icon.vue"
import emblem from "@/assets/oak-emblem.png"

// Chrome fires this before showing its own mini-infobar; holding on to the event is the
// only way to trigger the install sheet from our own button later.
const deferred = ref(null)
window.addEventListener("beforeinstallprompt", (e) => {
	e.preventDefault()
	deferred.value = e
})

const ios = isIos()
const inApp = isInAppBrowser()
const iosNonSafari = isIosNonSafari()
const installed = ref(false)
const copied = ref(false)
const appUrl = `${window.location.origin}/depot`

// Counted at mount, which happens exactly once per browser-mode load. The login bounce
// does not inflate it: `www/depot.py` sends a Guest to /login before the app ever boots,
// so a visit is only counted after they are already signed in.
const visits = noteBrowserVisit()
const repeat = visits > 1
const repeatBody = labels.installRepeatBody.replace("{n}", visits)

const steps = ios
	? [labels.installIosStep1, labels.installIosStep2, labels.installIosStep3]
	: [labels.installAndroidStep1, labels.installAndroidStep2]

async function install() {
	const e = deferred.value
	if (!e) return
	deferred.value = null
	e.prompt()
	const { outcome } = await e.userChoice
	// Accepting does not navigate this tab anywhere — the PWA is installed alongside it.
	// Say so, rather than dropping back to manual steps for something already done.
	// A dismissed prompt leaves the screen as it was, which is the whole point of the gate.
	if (outcome === "accepted") installed.value = true
}

async function copyLink() {
	try {
		await navigator.clipboard.writeText(appUrl)
	} catch (err) {
		// Webviews routinely withhold the clipboard API. The URL is printed under the
		// button precisely so it can still be copied by hand.
		return
	}
	copied.value = true
	setTimeout(() => (copied.value = false), 2000)
}
</script>
