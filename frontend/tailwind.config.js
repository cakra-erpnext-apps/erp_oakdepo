import frappeUIPreset from "frappe-ui/src/tailwind/preset"
import defaultTheme from "tailwindcss/defaultTheme"

// Every colour resolves through a CSS variable holding "R G B" channels, so one attribute
// on <html> repaints the app. Shades are the full 50-900 ramp: a shade nobody uses today
// costs one unused variable, while a shade that is MISSING renders as no colour at all
// (which is exactly how sky-* went unnoticed).
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]
const withVar = (name) => `rgb(var(--c-${name}) / <alpha-value>)`
const ramp = (name) => Object.fromEntries(SHADES.map((s) => [s, withVar(`${name}-${s}`)]))

export default {
	presets: [frappeUIPreset],
	content: [
		"./index.html",
		"./src/**/*.{vue,js,ts,jsx,tsx}",
		"./node_modules/frappe-ui/src/components/**/*.{vue,js,ts,jsx,tsx}",
		"../node_modules/frappe-ui/src/components/**/*.{vue,js,ts,jsx,tsx}",
	],
	theme: {
		extend: {
			// The whole palette is CSS-variable driven (values in main.css, one block per
			// theme). That is what makes dark mode a token swap instead of a rewrite: every
			// `bg-white` / `text-gray-900` / `bg-brand-50` already written across the app —
			// and the ones inside frappe-ui's own components, compiled by this same build —
			// resolves through a variable, so flipping `data-theme` on <html> re-colours the
			// entire PWA without touching a single template.
			//
			// `<alpha-value>` keeps the opacity modifiers working (`bg-paper/90` in the
			// sticky header, `bg-gray-900/40` behind a sheet), which a plain `var(--x)` colour
			// would silently break.
			//
			// `brand` = the orange sun (primary / identity), `leaf` = the green island +
			// wordmark (secondary / confirm), anchored on the exact logo hexes in light mode:
			// brand-500 #F97828, leaf-600 #078044.
			//
			// `paper` is the one NEW name: it is what `bg-white` used to mean — a card, a sheet,
			// the header — as opposed to literal white, which still exists and is still literal
			// (text on a coloured button, a ring around an avatar). Not called `surface`:
			// frappe-ui already owns that word as a namespace (`bg-surface-gray-2`), and a bare
			// `bg-surface` on top of it resolves to nothing at all.
			colors: {
				paper: withVar("paper"),
				gray: ramp("gray"),
				brand: ramp("brand"),
				leaf: ramp("leaf"),
				amber: ramp("amber"),
				red: ramp("red"),
				orange: ramp("orange"),
				blue: ramp("blue"),
				// `sky` and `indigo` are not in frappe-ui's palette at all, so the "Pending
				// Review" chips written in them across EIR / Cleaning / M&R were rendering with
				// no colour whatsoever. Defined here, they finally paint.
				sky: ramp("sky"),
				indigo: ramp("indigo"),
			},
			fontFamily: {
				sans: ['"Plus Jakarta Sans Variable"', ...defaultTheme.fontFamily.sans],
			},
			boxShadow: {
				card: "0 1px 2px 0 rgb(16 24 40 / 0.04), 0 1px 3px 0 rgb(16 24 40 / 0.06)",
				soft: "0 8px 24px -8px rgb(16 24 40 / 0.12)",
				header: "0 1px 2px 0 rgb(16 24 40 / 0.05)",
			},
			screens: {
				standalone: {
					raw: "(display-mode: standalone)",
				},
			},
			padding: {
				"safe-top": "env(safe-area-inset-top)",
				"safe-bottom": "env(safe-area-inset-bottom)",
			},
			keyframes: {
				"fade-in": {
					"0%": { opacity: "0" },
					"100%": { opacity: "1" },
				},
				"slide-up": {
					"0%": { opacity: "0", transform: "translateY(8px)" },
					"100%": { opacity: "1", transform: "translateY(0)" },
				},
				shimmer: {
					"100%": { transform: "translateX(100%)" },
				},
			},
			animation: {
				"fade-in": "fade-in 0.2s ease-out",
				"slide-up": "slide-up 0.25s ease-out both",
			},
		},
	},
	plugins: [],
}
