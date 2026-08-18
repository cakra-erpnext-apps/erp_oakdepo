// "Is this app running from the home screen, and does it need to be?"
//
// On mobile the answer must be yes, with no way past it. The browser tab is not a
// supported way to run this app: iOS only delivers Web Push to a PWA that was added to
// the Home Screen, so an operator left in Safari never hears about a job — and a job they
// never heard about is the failure this whole app exists to prevent. A tab also loses the
// home-screen icon they are told to tap at the start of a shift, which is how "the app is
// broken" reports start.
//
// The block is mobile-only on purpose. Requiring standalone everywhere would lock out
// supervisors working from a laptop, where installing buys nothing — the browser tab is
// already the app, and desktop push works without installing.
//
// There is deliberately no escape hatch. What replaces it is telling someone who genuinely
// CANNOT install (an in-app browser, Chrome on iOS) how to get to a browser that can, which
// is a real answer rather than a door into an unsupported mode.

export function isStandalone() {
	return (
		window.matchMedia("(display-mode: standalone)").matches ||
		// Safari never adopted display-mode; this non-standard flag is the iOS signal.
		window.navigator.standalone === true
	)
}

export function isIos() {
	const ua = navigator.userAgent
	// iPadOS 13+ reports itself as a Mac. Touch points is what separates it from a real
	// desktop, which must not be gated.
	return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
}

export function isMobile() {
	return isIos() || /Android/i.test(navigator.userAgent)
}

/**
 * Opened inside another app's built-in browser rather than a real one.
 *
 * This is the common case here, not an edge case: schedules and links get passed around on
 * WhatsApp, and tapping one opens WhatsApp's own webview. None of these can install a PWA —
 * there is no menu entry for it and `beforeinstallprompt` never fires — so the install
 * instructions would be a list of steps that do not exist on their screen. They need to be
 * sent to Chrome or Safari first.
 */
export function isInAppBrowser() {
	const ua = navigator.userAgent
	return (
		/\bwv\b/.test(ua) || // generic Android WebView marker: "...; wv) AppleWebKit..."
		/(FBAN|FBAV|FB_IAB|Instagram|Line\/|MicroMessenger|BytedanceWebview|musical_ly)/i.test(ua) ||
		/WhatsApp/i.test(ua)
	)
}

/**
 * Chrome / Firefox / Edge on iOS. They render with WebKit but Apple gives them no
 * "Add to Home Screen", so only Safari can complete an install on an iPhone.
 */
export function isIosNonSafari() {
	return isIos() && /CriOS|FxiOS|EdgiOS|OPiOS|Instagram|FBAV|FBAN/.test(navigator.userAgent)
}

export function mustInstall() {
	return isMobile() && !isStandalone()
}

// Someone landing here more than once did not install the first time they were asked.
// Usually that means they could not — an in-app browser, or steps they lost halfway — so
// from the second visit on the gate says so plainly, instead of repeating the same screen
// and letting them conclude the app is simply broken.
//
// localStorage, not sessionStorage: remembering across visits is the whole point. On iOS
// the home-screen app has its own storage, so installing does not clear Safari's counter —
// which is right, because opening the Safari link again IS another browser visit.
const VISIT_KEY = "depot.install.browserVisits"

/** Record one browser-mode open and return the running total (1 on the first). */
export function noteBrowserVisit() {
	try {
		const n = (parseInt(localStorage.getItem(VISIT_KEY), 10) || 0) + 1
		localStorage.setItem(VISIT_KEY, String(n))
		return n
	} catch (e) {
		return 1 // private mode has no memory, so never escalate
	}
}

/** Called once the app runs standalone — the ask worked, so stop counting against them. */
export function clearBrowserVisits() {
	try {
		localStorage.removeItem(VISIT_KEY)
	} catch (e) {
		/* nothing to forget */
	}
}
