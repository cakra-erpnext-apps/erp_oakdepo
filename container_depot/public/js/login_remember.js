// "Ingat saya" on the stock Frappe login page (/login) — loaded site-wide via the
// `web_include_js` hook, so it must no-op on every other website page.
//
// The checkbox stores the email AND the password in localStorage and refills both on the
// next visit. That is a deliberate, requested trade-off, so the risk is stated plainly:
// the password is readable in cleartext by anyone holding an unlocked device (devtools,
// or any other script that ends up running on this origin). On a depot tablet passed
// between operators, everyone who ticks this shares their login with the next person.
// Obfuscating the value would only hide that fact, not change it, so it is stored as-is.
// Untick the box and log in once to wipe what was stored.
(function () {
	const KEY = "oak_login_remember";

	function read() {
		try {
			const raw = localStorage.getItem(KEY);
			if (raw) return JSON.parse(raw);
			// The first build of this script remembered the bare email under its own key.
			const legacy = localStorage.getItem("oak_login_email");
			if (!legacy) return null;
			localStorage.removeItem("oak_login_email");
			return { usr: legacy, pwd: "" };
		} catch (e) {
			return null;
		}
	}

	function init() {
		const email = document.getElementById("login_email");
		const form = email && email.closest("form.form-login");
		if (!form || form.querySelector("#oak_remember_me")) return;

		// Frappe ships these inputs without a `name`; Chrome's password manager is happier
		// saving a form whose fields are named, and Frappe reads the values by id anyway.
		email.name = email.name || "username";
		const password = form.querySelector("#login_password");
		if (password) password.name = password.name || "password";

		const wrap = document.createElement("div");
		wrap.className = "form-group";
		wrap.innerHTML =
			'<label for="oak_remember_me" style="display:flex;align-items:center;gap:8px;margin:0;cursor:pointer">' +
			'<input type="checkbox" id="oak_remember_me" style="margin:0">' +
			"<span>Ingat saya</span></label>";
		const actions = form.querySelector(".page-card-actions");
		if (actions) actions.parentNode.insertBefore(wrap, actions);
		else form.appendChild(wrap);

		const box = wrap.querySelector("#oak_remember_me");
		const saved = read();
		box.checked = !!saved;
		if (saved) {
			if (!email.value) email.value = saved.usr || "";
			if (password && !password.value) password.value = saved.pwd || "";
			// Nothing left to type: put the operator on the button, not back in a filled field.
			if (email.value && password && password.value) {
				const button = form.querySelector(".btn-login");
				if (button) button.focus();
			} else if (email.value && password) {
				password.focus();
			}
		}

		form.addEventListener("submit", function () {
			if (box.checked) {
				localStorage.setItem(
					KEY,
					JSON.stringify({
						usr: (email.value || "").trim(),
						pwd: password ? password.value : "",
					})
				);
			} else {
				localStorage.removeItem(KEY);
			}
		});
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init);
	} else {
		init();
	}
})();
