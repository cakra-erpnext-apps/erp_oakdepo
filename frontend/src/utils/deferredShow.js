import { onUnmounted, ref } from "vue"

// A loading placeholder should not appear for a request that was never slow.
//
// Under 100 ms a response reads as instant, and a skeleton that paints and vanishes inside
// that window is its own kind of flicker — it makes a fast app look like it is struggling.
// So the placeholders hold back briefly and only show themselves if the wait turns out to be
// real. On the depot's good wifi most navigations never render one at all; on 3G every one of
// them does.
//
// 180 ms: past the point where a screen still feels instant, short enough that a hesitating
// tap is still answered quickly.
const DEFAULT_DELAY_MS = 180

/** `show` — false until `delay` has passed since mount. Cleaned up with the component. */
export function useDeferredShow(delay = DEFAULT_DELAY_MS) {
	const show = ref(false)
	const timer = setTimeout(() => {
		show.value = true
	}, delay)
	onUnmounted(() => clearTimeout(timer))
	return show
}
