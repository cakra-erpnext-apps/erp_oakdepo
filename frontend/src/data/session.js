import { computed, reactive } from "vue"

// Auth is the Frappe session cookie — there is no custom auth (PRD §3.3).
// The `user_id` cookie is set by Frappe on login; "Guest" means unauthenticated.
export function sessionUser() {
	const cookies = new URLSearchParams(document.cookie.split("; ").join("&"))
	let user = cookies.get("user_id")
	if (user === "Guest") user = null
	return user
}

// Send the browser through the standard Frappe login, returning to /depot.
export function redirectToLogin() {
	window.location.href = "/login?redirect-to=/depot"
}

// Desk and the PWA share one cookie jar. Logging out of Desk, or into it as someone else,
// swaps the cookie under an app that is still open — and on a phone the installed app is
// rarely relaunched, only brought back from the background. Everything the app holds in
// memory (this user, the CSRF token, the menu, the avatar) still belongs to the old login.
// So whenever the cookie says someone else, reload: /depot re-renders for the new login,
// or bounces a Guest to the login page.
export function checkSessionUser() {
	if (sessionUser() === session.user) return true
	window.location.reload()
	return false
}

export function watchSessionUser() {
	document.addEventListener("visibilitychange", () => {
		if (document.visibilityState === "visible") checkSessionUser()
	})
	window.addEventListener("focus", checkSessionUser)
	// Chromium only; catches a Desk tab switching accounts beside an app that stays in view.
	window.cookieStore?.addEventListener("change", checkSessionUser)
}

export const session = reactive({
	user: sessionUser(),
	isLoggedIn: computed(() => !!session.user),
	logout() {
		// Frappe's /api/method/logout requires POST + a valid CSRF token (a plain GET
		// navigation 403s). Mirror the CSRF pattern used for uploads, then go to login.
		fetch("/api/method/logout", {
			method: "POST",
			headers: { "X-Frappe-CSRF-Token": window.csrf_token || "" },
		}).finally(() => {
			window.location.href = "/login?redirect-to=/depot"
		})
	},
})
