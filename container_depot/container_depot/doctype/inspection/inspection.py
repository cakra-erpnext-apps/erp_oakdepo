import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from container_depot.container_depot.container_status import assert_container_active
import datetime

class Inspection(Document):
	def before_insert(self):
		"""Generate inspection ID"""
		self.inspection_id = self.generate_inspection_id()

	def generate_inspection_id(self):
		"""Kode EIR berurutan per tipe: EIR-IN-2026-00001 / EIR-OUT-2026-00001.

		Dulu kode ini potongan md5 acak (EIR-91194AC3) — tidak bisa dibaca, tidak bisa
		diurutkan, dan tidak berarti apa-apa buat orang lapangan. Serinya sengaja terpisah
		dari nama dokumen (EIR-.YYYY.-.#####) supaya nomor In dan Out jalan sendiri-sendiri.
		"""
		prefix = "EIR-OUT" if self.inspection_type == "EIR-Out" else "EIR-IN"
		return make_autoname(f"{prefix}-.YYYY.-.#####")

	def before_save(self):
		"""Auto-populate container number"""
		if self.container:
			container = frappe.get_doc("Container", self.container)
			self.container_no = container.container_no

	def validate(self):
		"""Validate inspection data"""
		# A retired tank takes no new work (container_status.assert_container_active);
		# only checked when the link is set or moved, so a finished order stays editable
		# after its tank leaves the fleet.
		if self.container and self.has_value_changed("container"):
			assert_container_active(self.container)
		self.drop_empty_photo_rows()
		self.stamp_container_booking()
		self.sync_has_damage()
		self.stamp_inspector()
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

	def sync_has_damage(self):
		"""Derive Has Damage from the log instead of trusting a second, editable copy of it.

		The checkbox and the rows were two sources for one fact and drifted both ways: ticked
		with an empty log (the form warned about it and left it), or rows added straight in
		the grid with the box untouched. Downstream that decides real things — the M&R
		follow-up on submit, and Hold Pending Clearance on an EIR-Out — so it has to read off
		the evidence.

		"Damage" here means what the PWA already means by it (``_build_damage_rows``): a row
		carrying a REAL defect code. A row stored only for a repair action or a remark, or one
		coded "v" (Acceptable), is a finding on a tank that is not damaged — matching
		``test_acceptable_skipped_and_repair_only_not_damage``.
		"""
		from container_depot.container_depot.eir import ACCEPTABLE_DAMAGE_CODE

		self.has_damage = 1 if any(
			(r.damage_type or "") not in ("", ACCEPTABLE_DAMAGE_CODE) for r in (self.damage_log or [])
		) else 0

	def stamp_inspector(self):
		"""Inspector = who WORKED the EIR, not who created the record.

		``work_started_by`` is stamped when the operator presses "Mulai" in the PWA, and that
		is the person answering for what the EIR says. The two differ routinely: Adm Ops opens
		the draft from the worklist (owner), the surveyor on the yard starts and fills it.
		Left as a free field it drifted to whoever typed last, so it is read-only on the form
		and written here.

		Falls back to what is already set, then to the creator, so the reqd field is never
		empty by the time Frappe checks it (validate runs before _validate_mandatory).
		"""
		self.inspector = self.get("work_started_by") or self.inspector or self.owner or frappe.session.user

	def stamp_container_booking(self):
		"""Record which Container Booking this EIR belongs to, resolved through its bon.

		The EIR is the root of the attribution chain — the Cleaning Order and M&R it spawns
		copy this value rather than re-walking the vouchers, so a bon that is later
		re-pointed (``eir.release_eirs_for_cancelled_order``) carries its orders with it on
		the next save.

		Recomputed on every save rather than only on insert, because ``referred_voucher``
		is assigned after the fact on two paths: the surveyor picking a bon in the PWA, and
		a cancelled bon being replaced. Read-only in the form, so there is no operator edit
		to preserve here — unlike the orders downstream.
		"""
		from container_depot.container_depot.booking_link import booking_of_voucher

		self.container_booking = booking_of_voucher(self.voucher_doctype, self.referred_voucher)

	# Photo tables on this doctype, as (child table fieldname, image fieldname).
	PHOTO_TABLES = (("exterior_photos", "photo_url"), ("item_photos", "photo"))

	def drop_empty_photo_rows(self):
		"""A photo row without a photo is not a row — remove it instead of refusing the save.

		Both image fields are ``reqd``, so an emptied row can never be saved anyway. Left
		alone, Frappe answers with "Photo is required" and leaves the user to find which of
		forty rows it meant; these records exist only to carry an image, so the honest
		response to a missing one is to drop the row.

		Runs here rather than only in the Desk client because every other way in — the PWA,
		the REST API, a data import — reaches the same tables. Ordering is safe: Frappe runs
		``validate`` (via run_before_save_methods) before ``_validate_mandatory``, so these
		rows are gone before the reqd check sees them.
		"""
		for table_fieldname, photo_fieldname in self.PHOTO_TABLES:
			rows = self.get(table_fieldname) or []
			kept = [r for r in rows if (r.get(photo_fieldname) or "").strip()]
			if len(kept) == len(rows):
				continue
			for idx, row in enumerate(kept, start=1):
				row.idx = idx
			self.set(table_fieldname, kept)

	def on_update(self):
		"""A DRAFT EIR-In is open work — the tank is not free to leave while one is on it.

		The status used to move only at submit, so an EIR raised by hand on a tank that had
		nothing open left it reading ``Available`` with an inspection in progress. Cleaning
		and M&R already recompute on every save; this closes the same hole for the EIR.
		Cheap: the recompute writes nothing when the tank is already in the right state.
		"""
		if self.inspection_type == "EIR-In" and self.docstatus == 0:
			from container_depot.container_depot.container_status import recompute_availability

			recompute_availability(self.container)

	def after_delete(self):
		# A deleted draft EIR is work that no longer exists — give the tank back.
		from container_depot.container_depot.container_status import recompute_availability

		recompute_availability(self.container)

	def on_cancel(self):
		"""Keep the ``status`` field in step with the docstatus so Desk + PWA never disagree.

		Cancelling (Void) leaves docstatus 2 but the status Select would otherwise still read
		"Submitted" — the record then looks live in the Desk form while the badge says
		cancelled. (``revert_to_draft`` writes docstatus/status raw, so it never fires this.)"""
		self.db_set("status", "Cancelled", update_modified=False)
		# Cancelled (docstatus 2) drops out of `container_open_orders`, so the tank it was
		# holding In_Depot has to be recomputed.
		from container_depot.container_depot.container_status import recompute_availability

		recompute_availability(self.container)

	def on_submit(self):
		"""Update container status + last cargo when inspection is submitted"""
		from container_depot.container_depot.container_activity import log_container_activity

		# Admin Ops has reviewed + submitted — clear the Pending Review flag on the status.
		self.db_set("status", "Submitted", update_modified=False)

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
			# Status is no longer set here — a dirty/damaged tank simply keeps the
			# container In_Depot via the open Cleaning/Repair order created below, and
			# recompute_availability (end of on_submit) flips it to Available once every
			# related order is done.
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

		# In-app notification (PWA + Desk bell) for EIR-In/EIR-Out.
		if self.inspection_type in ("EIR-In", "EIR-Out"):
			from container_depot.container_depot.notify import notify_eir_submitted

			notify_eir_submitted(self, container)

		# Empty-Dirty (undamaged) EIR-In → auto-create a Cleaning Order so the cleaning
		# team knows a tank is waiting, and notify them — but ONLY when the surveyor left
		# "Buat Cleaning Order" checked. (create_cleaning_order_from_eir itself no-ops for a
		# non-dirty tank, so the checkbox is the operator's opt-out.) The finished Cleaning
		# Order is itself the TANK OUT proof — see container_depot/cleaning.py.
		if self.inspection_type == "EIR-In" and self.get("create_cleaning_order"):
			self._ensure_cleaning_order(container)

		# Damaged EIR-In → auto-create a Draft M&R (Repair Order) so the M&R team can pick
		# the inventory parts to repair/replace, and notify them — but ONLY when the surveyor
		# left "Buat M&R" checked. The create call is a no-op when the EIR carries no real
		# damage finding, so the checkbox is the operator's opt-out.
		if self.inspection_type == "EIR-In" and self.get("create_repair_order"):
			self._ensure_repair_order_draft(container)

		# Presence-based status: now that this EIR is submitted and any follow-up
		# Cleaning/Repair orders exist, recompute In_Depot vs Available for the tank.
		if self.inspection_type == "EIR-In":
			from container_depot.container_depot.container_status import recompute_availability

			recompute_availability(self.container)

		# A clean EIR-Out submitted = the tank has LEFT the depot. This approval is the ONLY
		# thing that declares a departure (the operator-pressed "ACC Keluar" queue is gone),
		# so the gate-out runs from here: Container -> Gate_Out, the Gate Entry stamped and
		# closed, the bon completed once its last tank is out, gate/ops notified. Left last
		# on purpose — everything above describes the inspection, this is its consequence.
		# It throws (rolling the submit back) when the tank is not actually free to go, which
		# is the right refusal: the review must not sign a departure that cannot happen.
		if self.inspection_type == "EIR-Out" and self.get("out_outcome") == "Ready To Load":
			from container_depot.container_depot.gate import mark_gate_out

			mark_gate_out(
				container=self.container, eir_out=self.name, performed_by=self.get("inspector")
			)

	def _ensure_cleaning_order(self, container):
		"""Create (idempotently) a Pending Cleaning Order for this dirty tank and notify
		the cleaning team — only the first time, so re-submits don't spam."""
		from container_depot.container_depot import eir_followups
		from container_depot.container_depot.container_activity import log_container_activity
		from container_depot.container_depot.notify import notify_cleaning_order_created

		# Notify for a NEW order only. The create call is idempotent and answers with an
		# order that already existed whenever one does — this EIR's own from an earlier
		# submit, or another EIR's still open on the tank — and neither is news to the
		# cleaning team. Comparing against what was there beforehand is the one test that
		# covers both without asking which kind it was.
		before = set(frappe.get_all("Cleaning Order", filters={"container": container.name}, pluck="name"))
		order = eir_followups.create_cleaning_order_from_eir(self.name)
		if not order or order in before:
			return  # nothing created (not dirty / already filed) — don't re-notify
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
		from container_depot.container_depot import eir_followups
		from container_depot.container_depot.container_activity import log_container_activity
		from container_depot.container_depot.notify import notify_repair_order_created

		# New order only — same reasoning as _ensure_cleaning_order above.
		before = set(frappe.get_all("Repair Order", filters={"container": container.name}, pluck="name"))
		order = eir_followups.create_repair_order_from_eir(self.name)
		if not order or order in before:
			return  # nothing to repair / already filed — don't re-notify
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

		Clean = no new damage on the checklist. A clean EIR-Out flips the Order Muat to
		``Ready To Load``; a finding flips it to ``Hold`` and notifies the Ops Supervisor.
		The container status is NOT touched here — the gate-out at the end of ``on_submit``
		is what moves it, and it reads the ``out_outcome`` written below to decide. No
		"ready to load" ping is sent: on a clean EIR-Out the tank leaves in the same submit,
		so the gate-out notification is the one that tells the truth.

		The separate exterior-cleanliness and seal-integrity checks (PRO-OPS-08 §G.2/G.3)
		were dropped at the depot's request; the checklist findings are the only input now.
		"""
		reasons = []
		if self.has_damage:
			reasons.append("ada temuan kerusakan")

		outcome = "Ready To Load" if not reasons else "Hold Pending Clearance"
		self.db_set("out_outcome", outcome, update_modified=False)

		# Resolve the Order Muat this EIR-Out was raised against (auto-voucher set it).
		order_muat = self.referred_voucher if self.get("voucher_doctype") == "Order Muat" else None
		from container_depot.container_depot.notify import notify_eir_out_hold

		if outcome == "Ready To Load":
			# Intermediate state for a multi-tank bon: gate-out closes it to ``Completed``
			# once the LAST tank on it is out.
			if order_muat:
				frappe.db.set_value("Order Muat", order_muat, "order_status", "Ready To Load", update_modified=False)
		else:
			if order_muat:
				frappe.db.set_value("Order Muat", order_muat, "order_status", "Hold", update_modified=False)
			notify_eir_out_hold(self.container_no, order_muat, ", ".join(reasons), depot=self.depot)
