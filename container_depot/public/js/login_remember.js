// "Ingat saya" on the stock Frappe login page (/login) — loaded site-wide via the
// `web_include_js` hook, so it must no-op on every other website page.
//
// Scope, deliberately: this remembers the EMAIL only. The password is left to the
// browser/Android password manager, which already fires on this form (the inputs carry
// autocomplete="username"/"current-password") and which the depot's Android TWA inherits
// from Chrome via the verified assetlinks. Keeping the password out of localStorage means
// a shared depot tablet cannot hand the next person a working login through devtools.
(function () {
	const KEY = "oak_login_email";

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
			"<span>Ingat email saya</span></label>";
		const actions = form.querySelector(".page-card-actions");
		if (actions) actions.parentNode.insertBefore(wrap, actions);
		else form.appendChild(wrap);

		const box = wrap.querySelector("#oak_remember_me");
		const saved = localStorage.getItem(KEY);
		box.checked = !!saved;
		if (saved && !email.value) {
			email.value = saved;
			// Email is already filled in, so the only thing left to type is the password.
			if (password) password.focus();
		}

		form.addEventListener("submit", function () {
			if (box.checked) localStorage.setItem(KEY, (email.value || "").trim());
			else localStorage.removeItem(KEY);
		});
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init);
	} else {
		init();
	}
})();
