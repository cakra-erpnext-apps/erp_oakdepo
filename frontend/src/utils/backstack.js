// The phone's Back gesture, treated as "dismiss the thing on top".
//
// On a handset there is no Escape key. The Back gesture (or button) is the only dismiss an
// operator has, and until now it did the one thing it must never do: it left the screen.
// Opening a photo viewer and pressing Back closed the *page* behind the viewer; pressing it
// inside a half-filled survey threw the survey away and went Home.
//
// Anything that renders ON TOP of the current page — a photo viewer, a confirm sheet, a
// bottom sheet, an in-page detail view — registers a dismisser here while it is open. Back
// then closes the topmost one and the navigation is cancelled. With nothing registered Back
// behaves exactly as before, so leaving a page is still one press away.
//
// Routed detail views (Eir, Cleaning, M&R — the ones that put the open record
// in `?o=`) need none of this: their Back already pops a real history entry. This is for the
// views that live in a component ref, where the browser has no idea anything opened.

import { onUnmounted, watch } from "vue"

const dismissers = []

/**
 * Register `fn` as the current topmost dismisser. Returns the unregister function — call it
 * when the layer closes by any other route (its own X button, a submit, unmount), or Back
 * will keep trying to close something that is already gone.
 */
export function pushDismisser(fn) {
	dismissers.push(fn)
	let live = true
	return () => {
		if (!live) return
		live = false
		const i = dismissers.indexOf(fn)
		if (i !== -1) dismissers.splice(i, 1)
	}
}

/**
 * Wire the stack into the router. Must be installed BEFORE the app's other `beforeEach`
 * guards so it gets the first say on a Back press.
 */
export function installBackGuard(router) {
	// Only Back/Forward may dismiss. Tapping a tab in the bottom bar is a deliberate move to
	// another screen and must still go there on the first tap, open layers or not.
	let popped = false
	// Aborting a popstate navigation makes vue-router walk the history back to where it was,
	// which fires a second popstate that is ours, not the user's. Swallow exactly that one.
	let restoring = false

	window.addEventListener("popstate", () => {
		if (restoring) {
			restoring = false
			return
		}
		popped = true
	})

	router.beforeEach(() => {
		const wasBack = popped
		popped = false
		if (!wasBack || !dismissers.length) return true
		dismissers[dismissers.length - 1]()
		restoring = true
		return false
	})

	router.afterEach(() => {
		popped = false
	})
}

/**
 * A layer that is not a detail view — a photo viewer, a confirm sheet, a dropdown. Back
 * closes it; nothing else changes.
 *
 * `isOpen` is a ref/computed the layer already has; `close` is the function its own X button
 * calls, so Back and the X do exactly the same thing.
 */
export function useDismissOnBack(isOpen, close) {
	let unregister = null
	watch(isOpen, (open) => {
		if (open === !!unregister) return
		if (open) unregister = pushDismisser(close)
		else {
			unregister()
			unregister = null
		}
	})
	onUnmounted(() => unregister?.())
}

/**
 * An in-page detail view: the list stays mounted underneath and a component ref decides
 * which one is on screen. Two things the browser would have done for free if this were a
 * route, and does not do here:
 *
 *   Back closes the detail and returns to the list, instead of leaving the screen.
 *   Opening scrolls to the top — tapping the 20th row used to render the detail with the
 *   page still scrolled 2000px down, i.e. somewhere past the end of a shorter page.
 *
 * Closing puts the operator back on the row they tapped, which is the whole point of
 * remembering the offset: after finishing one tank they are usually going straight to the
 * next one next to it.
 */
export function useDetailView(isOpen, close) {
	let listY = 0
	let unregister = null
	watch(isOpen, (open) => {
		if (open === !!unregister) return
		if (open) {
			listY = window.scrollY
			window.scrollTo(0, 0)
			unregister = pushDismisser(close)
		} else {
			unregister()
			unregister = null
			restoreScroll(listY)
		}
	})
	onUnmounted(() => unregister?.())
}

// The list is re-rendering (and often refetching) as we scroll back, so its full height is
// not there on the frame the detail closes. Wait for the page to grow tall enough to hold
// the old offset, then stop — bounded, because a list that came back shorter never will.
function restoreScroll(y) {
	if (y <= 0) return
	let tries = 0
	const tick = () => {
		const maxY = document.documentElement.scrollHeight - window.innerHeight
		if (maxY >= y - 2 || ++tries > 30) {
			window.scrollTo(0, Math.min(y, Math.max(0, maxY)))
			return
		}
		requestAnimationFrame(tick)
	}
	requestAnimationFrame(tick)
}
