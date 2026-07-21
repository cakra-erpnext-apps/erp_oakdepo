import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate, now_datetime, today


CLEAN_CERT_TTL_DAYS = 30  # default validity window; per-Contract override planned for later.


class CleaningCertificate(Document):
	def before_insert(self):
		"""Auto-populate fields before insertion"""
		if not self.clean_date:
			self.clean_date = now_datetime()
		if not self.certified_by:
			self.certified_by = frappe.session.user or "Administrator"

		if self.container and not self.prior_cargo:
			self.prior_cargo = frappe.db.get_value("Container", self.container, "last_cargo")

	def before_save(self):
		# A statement-minted cert carries no time expiry (validity is anchored per EIR);
		# the issuer sets flags.no_expiry so we leave valid_until blank (= valid forever,
		# per _latest_valid_cleaning_cert / Order Muat, which skip the date check when blank).
		if not self.valid_until and not self.flags.get("no_expiry"):
			anchor = getdate(self.clean_date) if self.clean_date else getdate(today())
			self.valid_until = add_days(anchor, CLEAN_CERT_TTL_DAYS)

	def on_submit(self):
		"""Update container certification status upon submission"""
		from container_depot.operations.container_activity import log_container_activity

		if self.container:
			container_doc = frappe.get_doc("Container", self.container)
			container_doc.certification_status = "Completed"
			container_doc.save(ignore_permissions=True)
			log_container_activity(
				self.container, "Cleaning Certificate",
				reference_doctype=self.doctype, reference_name=self.name,
				performed_by=self.get("certified_by"),
				activity_time=self.get("clean_date"),
				summary=f"{self.get('cleaning_method') or 'Cleaning'} certificate, valid until {self.valid_until}",
			)

		# The tank is now certified clean — which is exactly what an Order Muat needs
		# before it can load, so the cleaning crew and ops are told.
		from container_depot.operations.notify import notify_cleaning_certificate_issued
		notify_cleaning_certificate_issued(self)

	def is_valid(self) -> bool:
		if not self.valid_until:
			return False
		return getdate(self.valid_until) >= getdate(today())
