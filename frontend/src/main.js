import { createApp } from "vue"
import App from "./App.vue"
import router from "./router"
import { pruneReads } from "@/data/cache"
import { watchSessionUser } from "@/data/session"
import { initTheme } from "@/utils/theme"
import { initHaptics } from "@/utils/haptics"

import {
	Button,
	FormControl,
	setConfig,
	frappeRequest,
	resourcesPlugin,
} from "frappe-ui"

import "./main.css"

// Before anything renders: the inline snippet in index.html already stamped the theme
// onto <html> so the boot splash paints in it; this takes the same state over and keeps
// tracking the OS setting from here on.
initTheme()
// One delegated listener for the whole app — see utils/haptics.js for why it is not a
// per-button directive.
initHaptics()
watchSessionUser()

const app = createApp(App)

setConfig("resourceFetcher", frappeRequest)
app.use(resourcesPlugin)

app.component("Button", Button)
app.component("FormControl", FormControl)

app.use(router)

// Register the minimal service worker so the app is installable (Add to Home
// Screen). The SW source lives at src/service-worker.js; Vite emits it under
// the build base, /assets/container_depot/ess/.
//
// `scope` is not cosmetic. Left at its default, a script served from /assets/ gets the
// scope /assets/container_depot/ess/ — which does not cover /depot, where the app
// actually runs. `navigator.serviceWorker.ready` then never resolves for this app, so
// enabling push hangs on "memproses" forever instead of failing, and a push aimed at the
// app has no worker to wake.
//
// Claiming a scope above the script's own path needs the server's permission:
// nginx sends `Service-Worker-Allowed: /depot` on this file. In `vite dev` there is no
// nginx, so registration fails there with a SecurityError — expected, and it costs dev
// nothing but push, which needs the production VAPID keys anyway.
function registerServiceWorker() {
	if (!("serviceWorker" in navigator)) return
	const swUrl = "/assets/container_depot/ess/service-worker.js"
	navigator.serviceWorker
		.register(swUrl, { type: "module", scope: "/depot" })
		.catch((err) => console.error("SW registration failed", err))
}

router.isReady().then(async () => {
	// In `vite dev` the Jinja boot block in index.html is not rendered, so pull
	// a dev boot context from the app's www controller (developer mode only).
	if (import.meta.env.DEV) {
		try {
			const boot = await frappeRequest({
				url: "/api/method/container_depot.www.depot.get_context_for_dev",
			})
			if (!window.frappe) window.frappe = {}
			window.frappe.boot = boot
		} catch (err) {
			console.warn("Dev boot fetch failed (are you logged in to the bench?)", err)
		}
	}
	registerServiceWorker()
	// Start the offline queue before the first screen paints: a handset that was closed
	// mid-shift with work still queued should be sending it while the operator is still
	// looking at the home screen, not waiting for them to reopen the form.
	// Also drops anything cached under a previous login — depot handsets change hands
	// between shifts and one operator's branch-scoped worklist is not the next one's.
	pruneReads()
	app.mount("#app")
})
