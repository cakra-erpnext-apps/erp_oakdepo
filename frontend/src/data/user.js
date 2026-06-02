import { createResource } from "frappe-ui"

// Confirms the logged-in user server-side (defence-in-depth over the cookie).
// frappe.auth.get_logged_user returns the user id or raises for Guest.
export const userResource = createResource({
	url: "frappe.auth.get_logged_user",
	cache: "logged_user",
	auto: false,
})
