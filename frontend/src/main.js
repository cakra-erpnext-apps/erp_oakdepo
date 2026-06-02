import { createApp } from "vue"
import App from "./App.vue"
import router from "./router"

import {
	Button,
	FormControl,
	setConfig,
	frappeRequest,
	resourcesPlugin,
} from "frappe-ui"

import "./main.css"

const app = createApp(App)

setConfig("resourceFetcher", frappeRequest)
app.use(resourcesPlugin)

app.component("Button", Button)
app.component("FormControl", FormControl)

app.use(router)

// Register the minimal service worker so the app is installable (Add to Home
// Screen). The SW source lives at src/service-worker.js; Vite emits it under
// the build base, /assets/container_depot/ess/.
function registerServiceWorker() {
	if (!("serviceWorker" in navigator)) return
	const swUrl = "/assets/container_depot/ess/service-worker.js"
	navigator.serviceWorker
		.register(swUrl, { type: "module" })
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
	app.mount("#app")
})
