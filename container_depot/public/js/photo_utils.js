// Copyright (c) 2026, Oak Depot Team and contributors
// Utilities for photo downloading and viewing across Desk.

frappe.provide('container_depot');

/**
 * Download a single photo given its URL and an optional target filename.
 * Uses blob download with fallback.
 */
container_depot.download_photo = function (url, filename) {
	if (!url) return;
	const cleanName = filename || url.split('/').pop().split('?')[0] || 'photo.jpg';

	fetch(url)
		.then((res) => {
			if (!res.ok) throw new Error('Network error');
			return res.blob();
		})
		.then((blob) => {
			const blobUrl = window.URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.style.display = 'none';
			a.href = blobUrl;
			a.download = cleanName;
			document.body.appendChild(a);
			a.click();
			setTimeout(() => {
				document.body.removeChild(a);
				window.URL.revokeObjectURL(blobUrl);
			}, 1000);
		})
		.catch(() => {
			const a = document.createElement('a');
			a.href = url;
			a.download = cleanName;
			a.target = '_blank';
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
		});
};

/**
 * Download all photos attached to a document as a ZIP file.
 */
container_depot.download_doc_photos = function (doctype, name) {
	if (!doctype || !name) return;
	const endpoint = `/api/method/container_depot.api.download_doc_photos?doctype=${encodeURIComponent(
		doctype
	)}&name=${encodeURIComponent(name)}`;
	window.open(endpoint, '_blank');
};
