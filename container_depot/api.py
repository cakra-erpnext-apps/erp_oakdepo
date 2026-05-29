"""
API Endpoints for Hermes/OpenClaw Agent + SST integration.

Hardening rules (Phase 1 — PRO-OPS-08):

- State-changing endpoints require an authenticated user. SST / agent traffic
  must authenticate as a user holding the ``Container Depot SST Service`` role
  using Frappe token auth (``Authorization: token <api_key>:<api_secret>``).
- Read-only endpoints that may stay guest are rate-limited.
- All voucher / container lookups are parameterized via ``frappe.db`` helpers.
- ``handle_webhook`` requires an ``X-Signature: sha256=<hex>`` HMAC over the
  raw request body, keyed by ``container_depot_webhook_secret`` (site_config).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime

# ---------------------------------------------------------------------------
# Helpers — auth, input validation, signature
# ---------------------------------------------------------------------------

CONTAINER_NO_RE = re.compile(r"^[A-Z0-9-]{1,15}$")
VOUCHER_ID_RE = re.compile(r"^VOUCH-[A-Z0-9-]{1,32}$")
MAX_WEBHOOK_BODY_BYTES = 16 * 1024  # 16 KB hard cap


def _require_authenticated_user() -> None:
	"""Defence-in-depth: reject Guest even if ``allow_guest`` is ever flipped."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)


def _normalize_container_no(value) -> str:
	"""Uppercase, validate ISO 11-char shape, and return the canonical form."""
	if not value or not isinstance(value, str):
		frappe.throw(_("container_no is required."), frappe.ValidationError)
	candidate = value.strip().upper()
	if not CONTAINER_NO_RE.match(candidate):
		frappe.throw(_("Invalid container_no format."), frappe.ValidationError)
	cleaned = candidate.replace("-", "").replace(" ", "")
	if len(cleaned) != 11:
		frappe.throw(
			_("container_no must be 11 ISO characters (got {0}).").format(len(cleaned)),
			frappe.ValidationError,
		)
	return candidate


def _assert_voucher_id(value) -> str:
	if not value or not isinstance(value, str):
		frappe.throw(_("voucher_id is required."), frappe.ValidationError)
	candidate = value.strip().upper()
	if not VOUCHER_ID_RE.match(candidate):
		frappe.throw(_("Invalid voucher_id format."), frappe.ValidationError)
	return candidate


def _parse_qr_payload(qr_data) -> str:
	"""Accept either a bare voucher id or the ``OAK|<voucher>|<type>|<client>``
	payload produced by :meth:`Voucher.generate_qr_data`. Returns the voucher id.
	"""
	if not qr_data or not isinstance(qr_data, str):
		frappe.throw(_("qr_data is required."), frappe.ValidationError)
	raw = qr_data.strip()
	if raw.upper().startswith("OAK|"):
		parts = raw.split("|")
		if len(parts) < 2 or not parts[1]:
			frappe.throw(_("Malformed OAK QR payload."), frappe.ValidationError)
		raw = parts[1]
	return _assert_voucher_id(raw)


def _verify_webhook_signature(raw_body: bytes, signature_header, secret: str) -> bool:
	"""Constant-time compare of HMAC-SHA256(secret, raw_body) vs header."""
	if not signature_header or not secret:
		return False
	received = signature_header.strip()
	if received.lower().startswith("sha256="):
		received = received[len("sha256="):]
	try:
		expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
	except Exception:
		return False
	return hmac.compare_digest(received.lower(), expected.lower())


def _enforce_webhook_signature() -> None:
	"""When called inside an HTTP request, require a valid signed body. When
	called as a plain Python function (tests / bench execute), pass through.
	"""
	req = getattr(frappe.local, "request", None)
	if req is None:
		return
	secret = frappe.conf.get("container_depot_webhook_secret")
	if not secret:
		frappe.throw(
			_("Webhook is not configured (missing container_depot_webhook_secret)."),
			frappe.AuthenticationError,
		)
	try:
		raw_body = req.get_data(cache=True) or b""
	except Exception:
		raw_body = b""
	if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
		frappe.throw(_("Webhook payload too large."), frappe.ValidationError)
	sig = None
	headers = getattr(req, "headers", None)
	if headers is not None:
		sig = headers.get("X-Signature") or headers.get("X-Hub-Signature-256")
	if not _verify_webhook_signature(raw_body, sig, secret):
		frappe.throw(_("Invalid webhook signature."), frappe.AuthenticationError)


# ---------------------------------------------------------------------------
# Voucher / QR Code Validation
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"], allow_guest=True)
@rate_limit(key="qr_data", limit=30, seconds=60)
def validate_qr(qr_data):
	"""Decode a QR payload (``OAK|VOUCH-XYZ|...`` or bare voucher id) and
	return voucher details. Read-only; safe to leave guest-accessible but
	rate-limited per IP to discourage enumeration.

	POST /api/v1/gate/validate-qr
	"""
	try:
		voucher_id = _parse_qr_payload(qr_data)
	except frappe.ValidationError as e:
		return {"valid": False, "error": str(e)}

	voucher_name = frappe.db.get_value("Voucher", {"voucher_id": voucher_id}, "name")
	if not voucher_name:
		return {"valid": False, "error": "Voucher not found"}

	doc = frappe.get_doc("Voucher", voucher_name)
	return {
		"valid": True,
		"voucher_id": doc.voucher_id,
		"voucher_type": doc.voucher_type,
		"client": doc.client,
		"principal": doc.principal,
		"payment_status": bool(doc.payment_status),
		"status": doc.status,
		"containers": [
			{
				"container_no": c.container_no,
				"status": c.status,
				"container_type": c.container_type,
			}
			for c in doc.expected_containers
		],
	}


# ---------------------------------------------------------------------------
# Gate Entry Operations
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def register_gate_entry(voucher_id, container_no, security_guard=None, truck_plate=None, driver_name=None):
	"""Log a container arrival at the gate. Authenticated only.

	POST /api/v1/gate/entry
	"""
	_require_authenticated_user()
	voucher_id = _assert_voucher_id(voucher_id)
	container_no = _normalize_container_no(container_no)

	try:
		voucher_name = frappe.db.get_value("Voucher", {"voucher_id": voucher_id}, "name")
		if not voucher_name:
			return {"success": False, "error": "Voucher not found"}
		voucher = frappe.get_doc("Voucher", voucher_name)

		if not voucher.payment_status:
			return {"success": False, "error": "Payment not verified for this voucher"}

		container_name = frappe.db.get_value("Container", {"container_no": container_no})
		if not container_name:
			container = frappe.get_doc({
				"doctype": "Container",
				"container_no": container_no,
				"container_type": voucher.expected_containers[0].container_type if voucher.expected_containers else "ISO Tank",
				"status": "Gate_In",
				"principal": voucher.principal,
			})
			# TODO(Phase 6): drop ignore_permissions once the SST service role is
			# wired and the install.py blanket grant is replaced.
			container.insert(ignore_permissions=True)
			container_name = container.name
		else:
			container = frappe.get_doc("Container", container_name)

		gate_entry = frappe.get_doc({
			"doctype": "Gate Entry",
			"voucher": voucher.name,
			"container": container_name,
			"container_no": container_no,
			"security_guard": security_guard or frappe.session.user,
			"truck_plate": truck_plate,
			"driver_name": driver_name,
			"gate_in_timestamp": now_datetime(),
			"inspection_status": "Pending",
		})
		gate_entry.insert(ignore_permissions=True)
		gate_entry.submit()

		for vc in voucher.expected_containers:
			if vc.container_no.upper() == container_no:
				vc.status = "Gate_In"
				vc.gate_in_status = "Pending"
				voucher.save()
				break

		return {
			"success": True,
			"gate_entry_id": gate_entry.gate_entry_id,
			"container_no": container_no,
			"container_status": "Gate_In",
		}

	except frappe.ValidationError:
		raise
	except Exception as e:
		return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Yard Operations (Reachstacker)
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"], allow_guest=True)
@rate_limit(key="voucher_id", limit=60, seconds=60)
def get_pending_lifts(voucher_id=None, container_no=None):
	"""Get containers pending lift for a voucher. Read-only.

	GET /api/v1/yard/pending-lifts
	"""
	try:
		containers = []

		if voucher_id:
			voucher_id = _assert_voucher_id(voucher_id)
			voucher_name = frappe.db.get_value("Voucher", {"voucher_id": voucher_id}, "name")
			if not voucher_name:
				return {"success": False, "error": "Voucher not found"}
			voucher = frappe.get_doc("Voucher", voucher_name)
			for vc in voucher.expected_containers:
				if vc.status in ["Expected", "Gate_In"]:
					containers.append({
						"container_no": vc.container_no,
						"status": vc.status,
						"container_type": vc.container_type,
						"suggested_zone": get_suggested_zone(vc.container_type, "Needs_Cleaning"),
					})

		elif container_no:
			container_no = _normalize_container_no(container_no)
			container_name = frappe.db.get_value("Container", {"container_no": container_no}, "name")
			if not container_name:
				return {"success": False, "error": "Container not found"}
			container = frappe.get_doc("Container", container_name)
			containers.append({
				"container_no": container.container_no,
				"status": container.status,
				"yard_zone": container.yard_zone,
			})

		return {"success": True, "containers": containers}

	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
	except Exception as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist(methods=["PATCH"])
def update_container_location(container_no, yard_zone, lifted_by=None):
	"""Update container location after lift. Authenticated only.

	PATCH /api/v1/yard/update-location
	"""
	_require_authenticated_user()
	container_no = _normalize_container_no(container_no)

	try:
		container_name = frappe.db.get_value("Container", {"container_no": container_no}, "name")
		if not container_name:
			return {"success": False, "error": "Container not found"}
		container = frappe.get_doc("Container", container_name)

		container.current_location = yard_zone
		container.yard_zone = yard_zone
		container.save(ignore_permissions=True)

		vouchers_active = frappe.db.get_all(
			"Voucher",
			filters={"status": ("in", ["Active", "Partial"])},
			pluck="name",
		)
		voucher_name = None
		if vouchers_active:
			voucher_name = frappe.db.get_value(
				"Voucher Container",
				{"container_no": container_no, "parent": ("in", vouchers_active)},
				"parent",
			)
		if voucher_name:
			voucher = frappe.get_doc("Voucher", voucher_name)
			for vc in voucher.expected_containers:
				if vc.container_no.upper() == container_no:
					vc.yard_location = yard_zone
					vc.lifted_by_reachstacker = lifted_by
					voucher.save(ignore_permissions=True)
					break

		return {
			"success": True,
			"container_no": container.container_no,
			"yard_zone": yard_zone,
		}

	except frappe.ValidationError:
		raise
	except Exception as e:
		return {"success": False, "error": str(e)}


def get_suggested_zone(container_type, service_type):
	if service_type == "Cleaning":
		return "Cleaning_Bay_C"
	elif service_type == "Repair":
		return "Workshop_D"
	elif service_type == "Survey":
		return "Survey_Lane_E"
	else:
		return "Storage_Yard_A"


# ---------------------------------------------------------------------------
# Inspection Operations
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def upload_inspection_evidence(container_no, photos, inspection_type="EIR-In", inspector=None):
	"""Receive inspection photos and save to storage. Authenticated only.

	POST /api/v1/inspection/upload-evidence
	"""
	_require_authenticated_user()
	container_no = _normalize_container_no(container_no)

	if isinstance(photos, str):
		try:
			photos = json.loads(photos)
		except json.JSONDecodeError:
			frappe.throw(_("photos must be a JSON array."), frappe.ValidationError)
	if not isinstance(photos, list):
		frappe.throw(_("photos must be a list."), frappe.ValidationError)

	try:
		container_name = frappe.db.get_value("Container", {"container_no": container_no}, "name")
		if not container_name:
			return {"success": False, "error": "Container not found"}
		container = frappe.get_doc("Container", container_name)

		inspection = frappe.get_doc({
			"doctype": "Inspection",
			"container": container.name,
			"container_no": container.container_no,
			"inspection_type": inspection_type,
			"inspector": inspector or frappe.session.user,
			"status": "Draft",
		})
		inspection.insert(ignore_permissions=True)

		photo_urls = []
		for photo in photos:
			if not isinstance(photo, dict):
				continue
			photo_url = f"/files/inspection/{container_no}/{photo.get('view', 'Unknown')}.jpg"
			inspection.append("exterior_photos", {
				"photo_view": photo.get("view", "Other"),
				"photo_url": photo_url,
				"timestamp": now_datetime(),
				"uploaded_by": inspector or frappe.session.user,
			})
			photo_urls.append(photo_url)

		inspection.save()

		return {
			"success": True,
			"inspection_id": inspection.inspection_id,
			"photo_urls": photo_urls,
		}

	except frappe.ValidationError:
		raise
	except Exception as e:
		return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def generate_qr_code(voucher_id):
	"""Generate a base64 PNG QR for a voucher payload (``OAK|<voucher_id>``)."""
	import qrcode
	from io import BytesIO

	qr_data = f"OAK|{voucher_id}"
	img = qrcode.make(qr_data)
	buffered = BytesIO()
	img.save(buffered, format="PNG")
	return base64.b64encode(buffered.getvalue()).decode()


# ---------------------------------------------------------------------------
# WhatsApp/Telegram Webhook Handlers
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def handle_webhook(platform=None, message=None, from_user=None, from_number=None, session_id=None):
	"""Handle incoming messages from WhatsApp/Telegram.

	Requires:
	- Authenticated user (any role) — typically the bot integration's API user.
	- ``X-Signature: sha256=<hex>`` over the raw body, signed with
	  ``container_depot_webhook_secret`` from site_config.

	POST /api/v1/webhook/message
	"""
	_require_authenticated_user()
	_enforce_webhook_signature()

	try:
		platform = platform or "whatsapp"
		from_user = from_user or frappe.session.user

		if not session_id:
			session_id = f"{platform}_{from_user}_{now_datetime().strftime('%Y%m%d')}"

		intent = detect_intent(message)
		response = process_intent(intent, message, from_user, session_id)

		return {
			"success": True,
			"session_id": session_id,
			"intent": intent,
			"response": response,
		}

	except frappe.ValidationError:
		raise
	except frappe.AuthenticationError:
		raise
	except Exception as e:
		return {"success": False, "error": str(e)}


def detect_intent(message):
	"""Detect user intent from natural language message."""
	message_lower = message.lower() if message else ""

	intents = {
		"check_status": ["status", "where is", "location", "check container", "container location"],
		"gate_in": ["gate in", "arrival", "arrive", "check in"],
		"gate_out": ["gate out", "departure", "depart", "check out", "release"],
		"upload_photo": ["upload", "photo", "picture", "image", "inspection"],
		"check_payment": ["payment", "paid", "voucher", "bon"],
		"cleaning_queue": ["cleaning", "clean", "queue", "bay"],
		"repair_status": ["repair", "damage", "fix", "gasket"],
		"help": ["help", "what can", "commands", "menu"],
	}

	for intent, keywords in intents.items():
		if any(keyword in message_lower for keyword in keywords):
			return intent

	return "unknown"


def process_intent(intent, message, from_user, session_id):
	intent_handlers = {
		"check_status": handle_check_status,
		"gate_in": handle_gate_in,
		"gate_out": handle_gate_out,
		"upload_photo": handle_upload_photo,
		"check_payment": handle_check_payment,
		"cleaning_queue": handle_cleaning_queue,
		"repair_status": handle_repair_status,
		"help": handle_help,
		"unknown": handle_unknown,
	}
	handler = intent_handlers.get(intent, handle_unknown)
	return handler(message, from_user, session_id)


def handle_check_status(message, from_user, session_id):
	container_match = re.search(r"([A-Z]{4}\d{6}-?\d)", message or "")
	if not container_match:
		return "Please provide a container number (e.g., STLU123456-7). What container would you like to check?"

	try:
		container_no = _normalize_container_no(container_match.group(1))
	except frappe.ValidationError:
		return "Container number doesn't look right. Please check the format (e.g., STLU123456-7)."

	container_name = frappe.db.get_value("Container", {"container_no": container_no}, "name")
	if not container_name:
		return f"Container {container_no} not found in the system."

	doc = frappe.get_doc("Container", container_name)
	response = f"*Container Status: {doc.container_no}*\n"
	response += f"Status: {(doc.status or '').replace('_', ' ')}\n"
	response += f"Location: {doc.current_location or 'Not assigned'}\n"
	response += f"Principal: {doc.principal or 'N/A'}\n"

	if doc.status == "Needs_Cleaning":
		response += "\n⚠️ Container is pending cleaning. Please proceed to inspection."
	elif doc.status == "Cleaning":
		response += "\n🧹 Container is currently being cleaned."
	elif doc.status == "Ready":
		response += "\n✅ Container is ready for gate-out."

	return response


def handle_gate_in(message, from_user, session_id):
	upper = (message or "").upper()
	voucher_match = re.search(r"VOUCH-[A-Z0-9]+", upper)
	container_match = re.search(r"([A-Z]{4}\d{6}-?\d)", upper)

	if not voucher_match:
		return "Please provide a voucher number (e.g., VOUCH-ABCD1234) to proceed with gate-in."

	try:
		voucher_id = _assert_voucher_id(voucher_match.group(0))
	except frappe.ValidationError:
		return "Voucher number format is invalid."

	voucher_name = frappe.db.get_value("Voucher", {"voucher_id": voucher_id}, "name")
	if not voucher_name:
		return f"Voucher {voucher_id} not found. Please verify the voucher number."

	voucher_doc = frappe.get_doc("Voucher", voucher_name)
	if not voucher_doc.payment_status:
		return "⚠️ Payment not verified for this voucher. Please contact the office."

	if not container_match:
		return "Please provide the container number (e.g., STLU123456-7) that has arrived."

	try:
		container_no = _normalize_container_no(container_match.group(1))
	except frappe.ValidationError:
		return "Container number format is invalid."

	result = register_gate_entry(
		voucher_id=voucher_id,
		container_no=container_no,
		security_guard=from_user,
	)
	if result.get("success"):
		return (
			f"✅ Gate-in registered successfully!\n\nContainer: {container_no}\n"
			f"Status: {result.get('container_status')}\n\nNext step: Proceed to inspection bay for EIR-In."
		)
	return f"❌ Gate-in failed: {result.get('error')}"


def handle_gate_out(message, from_user, session_id):
	container_match = re.search(r"([A-Z]{4}\d{6}-?\d)", (message or "").upper())
	if not container_match:
		return "Please provide a container number (e.g., STLU123456-7) for gate-out."

	try:
		container_no = _normalize_container_no(container_match.group(1))
	except frappe.ValidationError:
		return "Container number format is invalid."

	container_name = frappe.db.get_value("Container", {"container_no": container_no}, "name")
	if not container_name:
		return f"Container {container_no} not found."

	doc = frappe.get_doc("Container", container_name)
	if doc.status != "Ready":
		return (
			f"⚠️ Container {container_no} is not ready for gate-out.\n"
			f"Current status: {(doc.status or '').replace('_', ' ')}\n\nPlease complete all required services first."
		)
	return (
		f"✅ Container {container_no} is ready for gate-out.\n\n"
		"Please proceed to gate with the release voucher.\n"
		"Final inspection (EIR-Out) photos will be required."
	)


def handle_upload_photo(message, from_user, session_id):
	return (
		"📸 Photo upload feature. Please send the inspection photos along with:\n\n"
		"1. Container number (e.g., STLU123456-7)\n"
		"2. Photo view (Front/Back/Left/Right)\n"
		"3. Any damage notes (if applicable)"
	)


def handle_check_payment(message, from_user, session_id):
	voucher_match = re.search(r"VOUCH-[A-Z0-9]+", (message or "").upper())
	if not voucher_match:
		return "Please provide a voucher number (e.g., VOUCH-ABCD1234) to check payment status."

	try:
		voucher_id = _assert_voucher_id(voucher_match.group(0))
	except frappe.ValidationError:
		return "Voucher number format is invalid."

	voucher_name = frappe.db.get_value("Voucher", {"voucher_id": voucher_id}, "name")
	if not voucher_name:
		return f"Voucher {voucher_id} not found."

	doc = frappe.get_doc("Voucher", voucher_name)
	response = f"*Voucher Details: {doc.voucher_id}*\n"
	response += f"Type: {(doc.voucher_type or '').replace('_', ' ')}\n"
	response += f"Client: {doc.client}\n"
	response += f"Principal: {doc.principal or 'N/A'}\n"

	if doc.payment_status:
		response += "\n✅ Payment: VERIFIED\n\nYou may proceed with gate-in."
	else:
		response += "\n❌ Payment: PENDING\n\nPlease complete payment before gate-in."

	if doc.expected_containers:
		response += "\n\n*Containers:*\n"
		for c in doc.expected_containers:
			response += f"- {c.container_no}: {(c.status or '').replace('_', ' ')}\n"

	return response


def handle_cleaning_queue(message, from_user, session_id):
	cleaning_orders = frappe.db.get_all(
		"Cleaning Order",
		filters={"status": "Pending"},
		fields=["name", "container", "priority", "status", "creation"],
		order_by="priority desc, creation asc",
		limit_page_length=10,
	)
	if not cleaning_orders:
		return "🧹 No containers currently pending cleaning."

	response = "*Cleaning Queue (Pending):*\n\n"
	for i, order in enumerate(cleaning_orders, 1):
		response += f"{i}. Container: {order.container}\n"
		response += f"   Priority: {order.priority} | Status: {order.status}\n\n"
	return response


def handle_repair_status(message, from_user, session_id):
	container_match = re.search(r"([A-Z]{4}\d{6}-?\d)", (message or "").upper())
	if not container_match:
		return "Please provide a container number (e.g., STLU123456-7) to check repair status."

	try:
		container_no = _normalize_container_no(container_match.group(1))
	except frappe.ValidationError:
		return "Container number format is invalid."

	container_name = frappe.db.get_value("Container", {"container_no": container_no}, "name")
	if not container_name:
		return f"Container {container_no} not found."

	doc = frappe.get_doc("Container", container_name)
	response = f"*Repair Status: {container_no}*\n"
	response += f"Current Status: {(doc.status or '').replace('_', ' ')}\n"

	if doc.status == "Needs_Repair":
		response += f"\n⚠️ Container needs repair.\nLocation: {doc.current_location or 'Workshop'}\n"
	elif doc.status == "Repairing":
		response += f"\n🔧 Repair in progress.\nLocation: {doc.current_location or 'Workshop'}\n"
	else:
		response += "\nNo active repair work.\n"
	return response


def handle_help(message, from_user, session_id):
	return """🤖 *Oak Depot Assistant - Help Menu*

*Available Commands:*

📍 *Check Status*
   "What is the status of STLU123456-7?"
   "Where is container ABCD123456-7?"

🚪 *Gate-In*
   "Gate in STLU123456-7 with voucher VOUCH-ABCD1234"
   "Container arrived, voucher VOUCH-ABCD1234"

💰 *Check Payment*
   "Check payment for VOUCH-ABCD1234"
   "Is VOUCH-ABCD1234 paid?"

🧹 *Cleaning Queue*
   "Show cleaning queue"
   "What's in the cleaning bay?"

🔧 *Repair Status*
   "Repair status for STLU123456-7"

📸 *Upload Photos*
   "Upload inspection photo for STLU123456-7"

❓ *Help*
   "Help" or "What can you do?"

*Tip:* Always include container numbers (e.g., STLU123456-7) or voucher numbers (e.g., VOUCH-ABCD1234) in your messages.
"""


def handle_unknown(message, from_user, session_id):
	return """🤔 I'm not sure what you're asking for.

Please try one of these:
- "Check status of STLU123456-7"
- "Gate in with voucher VOUCH-ABCD1234"
- "Check payment for VOUCH-ABCD1234"
- "Show cleaning queue"
- "Help" for more commands
"""


# ---------------------------------------------------------------------------
# Agent Skills Definition (for Hermes/OpenClaw)
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"], allow_guest=True)
@rate_limit(limit=10, seconds=60)
def get_agent_skills():
	"""Return available agent skills for the Hermes/OpenClaw integration.

	GET /api/v1/agent/skills
	"""
	skills = [
		{
			"name": "validate_qr",
			"endpoint": "/api/v1/gate/validate-qr",
			"method": "POST",
			"auth": "guest (rate-limited)",
			"description": "Decode QR code and validate voucher. Returns voucher details including payment status and expected containers.",
			"parameters": ["qr_data"],
		},
		{
			"name": "register_gate_entry",
			"endpoint": "/api/v1/gate/entry",
			"method": "POST",
			"auth": "authenticated (SST service user)",
			"description": "Register container gate-in at security checkpoint. Creates gate entry record and updates container status.",
			"parameters": ["voucher_id", "container_no", "security_guard", "truck_plate", "driver_name"],
		},
		{
			"name": "get_pending_lifts",
			"endpoint": "/api/v1/yard/pending-lifts",
			"method": "GET",
			"auth": "guest (rate-limited)",
			"description": "Get list of containers pending lift for a voucher. Returns container numbers, status, and suggested yard zones.",
			"parameters": ["voucher_id", "container_no"],
		},
		{
			"name": "update_container_location",
			"endpoint": "/api/v1/yard/update-location",
			"method": "PATCH",
			"auth": "authenticated (SST service user)",
			"description": "Update container yard location after reachstacker lift. Updates both container and voucher records.",
			"parameters": ["container_no", "yard_zone", "lifted_by"],
		},
		{
			"name": "upload_inspection_evidence",
			"endpoint": "/api/v1/inspection/upload-evidence",
			"method": "POST",
			"auth": "authenticated (SST service user)",
			"description": "Upload inspection photos (EIR-In/EIR-Out). Saves photos and returns URLs.",
			"parameters": ["container_no", "photos", "inspection_type", "inspector"],
		},
		{
			"name": "handle_webhook",
			"endpoint": "/api/v1/webhook/message",
			"method": "POST",
			"auth": "authenticated + HMAC X-Signature",
			"description": "Process natural language messages from WhatsApp/Telegram. Auto-detects intent and routes to appropriate handler.",
			"parameters": ["platform", "message", "from_user", "from_number", "session_id"],
		},
		{
			"name": "get_agent_skills",
			"endpoint": "/api/v1/agent/skills",
			"method": "GET",
			"auth": "guest (rate-limited)",
			"description": "Return available agent skills and endpoint definitions for integration.",
			"parameters": [],
		},
	]

	return {"success": True, "skills": skills}
