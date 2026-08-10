// "Is this app running from the home screen, and does it need to be?"
//
// The block is mobile-only on purpose. Requiring standalone everywhere would lock out
// supervisors working from a laptop, where installing a PWA buys nothing — the browser
// tab is already the app, and desktop push works without installing.
//
// On iPhone it is not merely tidier to install: iOS only delivers Web Push to a PWA that
// was added to the Home Screen, so an operator left in Safari would never hear a job.

const SKIP_KEY = "depot.install.skipped"

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

// Session-scoped, not localStorage: someone who could not install today should still be
// asked tomorrow. Dismissing is an escape hatch, not a preference.
export function markInstallSkipped() {
	try {
		sessionStorage.setItem(SKIP_KEY, "1")
	} catch (e) {
		/* private mode — the gate simply reappears */
	}
}

export function installSkipped() {
	try {
		return sessionStorage.getItem(SKIP_KEY) === "1"
	} catch (e) {
		return false
	}
}

export function mustInstall() {
	return isMobile() && !isStandalone() && !installSkipped()
}
