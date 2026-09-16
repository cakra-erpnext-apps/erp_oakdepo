// Touch feedback — the tick a handset gives when a control is actually hit.
//
// Operators run this app in gloves, in the sun, with the phone at arm's length: the visual
// press state on a button is frequently not seen at all, so a tap that missed and a tap that
// landed feel identical. One 10 ms buzz on press removes that doubt without a sound anyone
// has to hear over a yard.
//
// Delegated from the document, once, rather than a directive every button has to remember to
// carry — a control added next month gets the feedback for free, and there is no per-component
// state to leak. Capture phase so a handler that stops propagation (menus, sheets) still ticks.
//
// `pointerdown`, not `click`: the feedback has to arrive with the finger, not after whatever
// the button does. Touch only — a mouse or stylus press has nothing to vibrate.
//
// ponytail: no on/off setting. The Vibration API is already silenced by the phone's own
// switch (Android drops `navigator.vibrate` calls in silent/DND per the user's setting), so an
// in-app toggle would be a second, worse copy of a control the operator already has.

const TAP_MS = 10

// Things a finger presses and expects something to happen. `.oak-*` are this app's own
// classes; the rest is the plain HTML the pages are otherwise built from.
const PRESSABLE = "button, a, [role='button'], label, summary, select, .oak-btn, .oak-chip, .oak-tile"

export function haptic(ms = TAP_MS) {
	// Guarded: iOS Safari has no Vibration API at all, and a disallowed call throws in
	// some embedded webviews rather than returning false.
	try {
		navigator.vibrate?.(ms)
	} catch {
		/* best effort — feedback is never worth an error */
	}
}

export function initHaptics() {
	document.addEventListener(
		"pointerdown",
		(e) => {
			if (e.pointerType !== "touch") return
			const el = e.target?.closest?.(PRESSABLE)
			if (!el || el.disabled || el.getAttribute("aria-disabled") === "true") return
			haptic()
		},
		{ capture: true, passive: true }
	)
}
