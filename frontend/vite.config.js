import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { VitePWA } from "vite-plugin-pwa"
import frappeui from "frappe-ui/vite"

import path from "path"
import fs from "fs"

// Container Depot ESS PWA — mirrors the hrms/frontend setup.
// Build output lands in ../container_depot/public/ess (served by Frappe as
// /assets/container_depot/ess/). The www/depot.html entry is produced by the
// `copy-html-entry` script after build, mounting the app at the /depot route.
export default defineConfig({
	server: {
		port: 8081,
		proxy: getProxyOptions(),
		allowedHosts: true,
	},
	plugins: [
		vue(),
		frappeui(),
		VitePWA({
			// We ship our own static manifest (public/manifest.json) and a minimal
			// hand-written service worker, so let the plugin only inject the
			// precache manifest into our SW source — it does not generate its own.
			strategies: "injectManifest",
			srcDir: "src",
			filename: "service-worker.js",
			injectRegister: null,
			manifest: false,
			injectManifest: {
				globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
			},
			devOptions: {
				enabled: true,
				type: "module",
			},
		}),
	],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
	build: {
		outDir: "../container_depot/public/ess",
		emptyOutDir: true,
		target: "es2015",
		sourcemap: true,
		rollupOptions: {
			output: {
				manualChunks: {
					"frappe-ui": ["frappe-ui"],
				},
			},
		},
	},
	optimizeDeps: {
		// Mirror hrms/frontend: pre-bundle frappe-ui's transitive CJS deps so the
		// dev server doesn't choke on them.
		include: ["frappe-ui > feather-icons", "showdown", "engine.io-client"],
	},
})

// Mirror of the hrms dev proxy: discover the bench's common_site_config.json by
// walking up to a directory that has both `sites/` and `apps/`, then proxy
// Frappe routes (app/login/api/assets/files/private) to its webserver port.
function getProxyOptions() {
	const config = getCommonSiteConfig()
	const webserver_port = config ? config.webserver_port : 8000
	if (!config) {
		console.log("No common_site_config.json found, using default port 8000")
	}
	return {
		"^/(app|login|api|assets|files|private)": {
			target: `http://127.0.0.1:${webserver_port}`,
			ws: true,
			router: function (req) {
				const site_name = req.headers.host.split(":")[0]
				return `http://${site_name}:${webserver_port}`
			},
		},
	}
}

function getCommonSiteConfig() {
	let currentDir = path.resolve(".")
	// traverse up till we find frappe-bench with a sites directory
	while (currentDir !== "/") {
		if (
			fs.existsSync(path.join(currentDir, "sites")) &&
			fs.existsSync(path.join(currentDir, "apps"))
		) {
			let configPath = path.join(currentDir, "sites", "common_site_config.json")
			if (fs.existsSync(configPath)) {
				return JSON.parse(fs.readFileSync(configPath))
			}
			return null
		}
		currentDir = path.resolve(currentDir, "..")
	}
	return null
}
