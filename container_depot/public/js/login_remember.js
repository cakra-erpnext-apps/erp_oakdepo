// Checkbox "Keep me signed in on this device" di /login — kotaknya ada di markup
// (www/login.html), skrip ini yang menyimpan dan mengisi ulang isinya. Dimuat
// site-wide lewat hook `web_include_js`, jadi harus diam di halaman web lain.
//
// Yang disimpan di localStorage adalah email DAN sandi, lalu diisikan lagi pada
// kunjungan berikutnya. Itu memang yang diminta, jadi risikonya ditulis terang:
// sandinya terbaca apa adanya oleh siapa pun yang memegang perangkat tidak
// terkunci (devtools, atau skrip lain yang kebetulan jalan di origin ini). Di
// tablet depo yang berpindah tangan, yang mencentang ini berbagi login dengan
// orang berikutnya. Menyamarkan nilainya hanya menutupi kenyataan itu, bukan
// mengubahnya, jadi disimpan apa adanya. Lepas centangnya lalu login sekali untuk
// menghapus yang tersimpan.
(function () {
	const KEY = "oak_login_remember";

	function read() {
		try {
			const raw = localStorage.getItem(KEY);
			if (raw) return JSON.parse(raw);
			// Versi pertama skrip ini menyimpan email saja di key-nya sendiri.
			const legacy = localStorage.getItem("oak_login_email");
			if (!legacy) return null;
			localStorage.removeItem("oak_login_email");
			return { usr: legacy, pwd: "" };
		} catch (e) {
			return null;
		}
	}

	function init() {
		const box = document.getElementById("oak_remember_me");
		const form = box && box.closest("form.form-login");
		if (!form) return;

		const email = form.querySelector("#login_email");
		const password = form.querySelector("#login_password");
		if (!email) return;

		// Frappe mengirim input ini tanpa `name`; password manager Chrome lebih senang
		// menyimpan form yang field-nya bernama, dan Frappe sendiri membaca nilainya
		// lewat id.
		email.name = email.name || "username";
		if (password) password.name = password.name || "password";

		const saved = read();
		box.checked = !!saved;
		if (saved) {
			if (!email.value) email.value = saved.usr || "";
			if (password && !password.value) password.value = saved.pwd || "";
			// Tidak ada lagi yang perlu diketik: taruh operator di tombol, bukan kembali
			// ke field yang sudah terisi.
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
