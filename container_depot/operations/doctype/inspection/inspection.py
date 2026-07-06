import frappe
from frappe.model.document import Document
import datetime
import hashlib

class Inspection(Document):
	def before_insert(self):
		"""Generate inspection ID"""
		self.inspection_id = self.generate_inspection_id()

	def generate_inspection_id(self):
		"""Generate unique inspection ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"EIR-{unique}"

	def before_save(self):
		"""Auto-populate container number"""
		if self.container:
			container = frappe.get_doc("Container", self.container)
			self.container_no = container.container_no

	def validate(self):
		"""Validate inspection data"""
		# Recommend the 4 exterior views for EIR-In — but only once the surveyor has
		# started uploading them (1-3 present). Don't nag empty drafts (the PWA EIR uses
		# per-item photos and auto-creates an empty draft on fetch).
		if self.inspection_type == "EIR-In":
			exterior_views = [p.photo_view for p in self.exterior_photos if p.photo_view in ["Front", "Back", "Left", "Right"]]
			if 0 < len(exterior_views) < 4:
				frappe.msgprint(f"Warning: Only {len(exterior_views)} exterior photos uploaded. 4 views (Front, Back, Left, Right) recommended for EIR-In.")

		# Bulk "foto cepat" (item_photos without a checklist item) still need sorting.
		# Recomputed on every save — including when the admin assigns the last one → 0 —
		# so the list filter "Ada Foto Belum Disortir" stays accurate.
		self.has_unsorted_photos = 1 if any(not p.checklist_item for p in self.item_photos) else 0

	def on_submit(self):
		"""Update container status + last cargo when inspection is submitted"""
		from container_depot.operations.container_activity import log_container_activity

		container = frappe.get_doc("Container", self.container)
		from_status = container.status

		# Snapshot the pre-submit container state so a later "Kembalikan ke Draft"
		# (eir.revert_to_draft) can undo exactly what this EIR changed.
		self.db_set("container_status_before_submit", from_status, update_modified=False)
		self.db_set("container_last_cargo_before_submit", container.last_cargo, update_modified=False)

		# Cargo recorded on the EIR updates the master's Last Cargo on submit only —
		# drafts never touch the master. Set before any save below.
		cargo_changed = bool(self.get("cargo")) and container.last_cargo != self.cargo
		if cargo_changed:
			container.last_cargo = self.cargo

		if self.inspection_type == "EIR-In":
			container.eir_in_date = datetime.datetime.now()
			# A dirty tank (no damage) for which the surveyor opted to create a Cleaning
			# Order is queued straight for cleaning. A damaged tank — or one where cleaning
			# was unchecked — stays in inspecting (repair routing handled separately).
			if self.get("create_cleaning_order") and self.get("tank_status") == "Empty Dirty" and not self.has_damage:
				container.status = "Pending_Cleaning"
				container.cleaning_status = "Pending"
			else:
				container.status = "Inspecting"
			self._save_container(container)
		elif self.inspection_type == "EIR-Out":
			# Record the gate-out inspection date on the container (mirrors EIR-In).
			container.eir_out_date = datetime.datetime.now()
			self._save_container(container)
			# Score readiness + signal Ready To Load / Hold on the Order Muat.
			self._apply_eir_out_outcome()
		elif cargo_changed:
			# Some other type with a cargo change — persist it.
			self._save_container(container)

		outcome = [p for p in (self.get("tank_status"), "damage found" if self.has_damage else None) if p]
		log_container_activity(
			self.container, "Inspection (EIR)",
			reference_doctype=self.doctype, reference_name=self.name,
			from_status=from_status, to_status=container.status,
			performed_by=self.get("inspector"),
			summary=f"{self.inspection_type}" + (": " + ", ".join(outcome) if outcome else ""),
		)

		# In-app notification (PWA + Desk bell) for EIR-In/EIR-Out — carries the
		# placement target category derived from THIS EIR (damage > Empty Dirty > Empty Clean).
		if self.inspection_type in ("EIR-In", "EIR-Out"):
			from container_depot.operations.notify import notify_eir_submitted
			from container_depot.operations.yard import _target_category

			category = _target_category(
				container,
				{"damage_count": 1 if self.has_damage else 0, "tank_status": self.get("tank_status")},
			)
			notify_eir_submitted(self, container, category)

		# Empty-Dirty (undamaged) EIR-In → auto-create a Cleaning Order so the cleaning
		# team knows a tank is waiting, and notify them — but ONLY when the surveyor left
		# "Buat Cleaning Order" checked. (create_cleaning_order_from_eir itself no-ops for a
		# non-dirty tank, so the checkbox is the operator's opt-out.) After cleaning, a
		# Cleaning Statement issues the Cleaning Certificate — see operations/cleaning.py.
		if self.inspection_type == "EIR-In" and self.get("create_cleaning_order"):
			self._ensure_cleaning_order(container)

		# Damaged EIR-In → auto-create a Draft M&R (Repair Order) so the M&R team can pick
		# the inventory parts to repair/replace, and notify them — but ONLY when the surveyor
		# left "Buat M&R" checked. The create call is a no-op when the EIR carries no real
		# damage finding, so the checkbox is the operator's opt-out.
		if self.inspection_type == "EIR-In" and self.get("create_repair_order"):
			self._ensure_repair_order_draft(container)

	def _ensure_cleaning_order(self, container):
		"""Create (idempotently) a Pending Cleaning Order for this dirty tank and notify
		the cleaning team — only the first time, so re-submits don't spam."""
		from container_depot.operations import eir_followups
		from container_depot.operations.container_activity import log_container_activity
		from container_depot.operations.notify import notify_cleaning_order_created

		had_open = frappe.db.exists(
			"Cleaning Order", {"container": container.name, "status": ["in", ["Pending", "In_Progress"]]}
		)
		order = eir_followups.create_cleaning_order_from_eir(self.name)
		if not order or had_open:
			return  # nothing created (not dirty / already queued) — don't re-notify
		log_container_activity(
			container.name, "Cleaning",
			reference_doctype="Cleaning Order", reference_name=order,
			to_status=container.status,
			performed_by=self.get("inspector"),
			summary="Cleaning order auto-created from Empty-Dirty EIR",
		)
		notify_cleaning_order_created(order)

	def _ensure_repair_order_draft(self, container):
		"""Create (idempotently) a Draft M&R for a damaged tank and notify the M&R team —
		only the first time, so re-submits don't spam. No-op when the EIR has no real
		damage finding (``create_repair_order_from_eir`` returns ``None``)."""
		from container_depot.operations import eir_followups
		from container_depot.operations.container_activity import log_container_activity
		from container_depot.operations.notify import notify_repair_order_created

		had_open = bool(eir_followups.open_repair_order(container.name))
		order = eir_followups.create_repair_order_from_eir(self.name)
		if not order or had_open:
			return  # nothing to repair / already in play — don't re-notify
		log_container_activity(
			container.name, "Repair",
			reference_doctype="Repair Order", reference_name=order,
			to_status=container.status,
			performed_by=self.get("inspector"),
			summary="M&R draft auto-created from EIR damage",
		)
		notify_repair_order_created(order)

	def _save_container(self, container):
		# Controller-driven status change: bypass the manual-transition guard.
		frappe.flags.in_status_automation = True
		try:
			container.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

	def _apply_eir_out_outcome(self):
		"""Score an EIR-Out's readiness and signal it on the referenced Order Muat.

		Clean = exterior Clean + seals intact + cleaning cert valid + no new damage. A clean
		EIR-Out flips the Order Muat to ``Ready To Load`` and notifies Operator Kalmar; any
		finding flips it to ``Hold`` and notifies the Ops Supervisor. The container status is
		NOT touched here (it stays on the OUT path; gate-out is the final move) — readiness
		lives on the Order Muat, and gate-out enforces a clean EIR-Out (see operations/gate)."""
		from frappe.utils import getdate, today

		# Cleaning certificate validity (blank valid_until = statement-minted = valid forever,
		# matching the Order Muat gate).
		vu = self.get("cleaning_cert_valid_until")
		cert_valid = bool(self.get("cleaning_cert")) and ((not vu) or getdate(vu) >= getdate(today()))

		reasons = []
		if (self.get("exterior_condition") or "") != "Clean":
			reasons.append(f"eksterior {self.get('exterior_condition') or 'belum dinilai'}")
		if not self.get("seals_intact"):
			reasons.append("segel tidak lengkap/utuh")
		if not cert_valid:
			reasons.append("cleaning certificate tidak valid")
		if self.has_damage:
			reasons.append("ada temuan kerusakan")

		outcome = "Ready To Load" if not reasons else "Hold Pending Clearance"
		self.db_set("out_outcome", outcome, update_modified=False)

		# Resolve the Order Muat this EIR-Out was raised against (auto-voucher set it).
		order_muat = self.referred_voucher if self.get("voucher_doctype") == "Order Muat" else None
		from container_depot.operations.notify import notify_eir_out_hold, notify_ready_to_load

		if outcome == "Ready To Load":
			if order_muat:
				frappe.db.set_value("Order Muat", order_muat, "order_status", "Ready To Load", update_modified=False)
			notify_ready_to_load(self.container_no, order_muat, depot=self.depot)
		else:
			if order_muat:
				frappe.db.set_value("Order Muat", order_muat, "order_status", "Hold", update_modified=False)
			notify_eir_out_hold(self.container_no, order_muat, ", ".join(reasons), depot=self.depot)
