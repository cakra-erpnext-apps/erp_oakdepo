"""
API Endpoints for Hermes/OpenClaw Agent + SST integration.

Hardening rules (Phase 1 — PRO-OPS-08):

- State-changing endpoints require an authenticated user. SST / agent traffic
  must authenticate as a user holding the ``Container Depot SST Service`` role
  using Frappe token auth (``Authorization: token <api_key>:<api_secret>``).
- Read-only endpoints that may stay guest are rate-limited.
- All Booking Code / container lookups are parameterized via ``frappe.db`` helpers.
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

from container_depot.operations.user_branch import assert_in_user_branch

# ---------------------------------------------------------------------------
# Helpers — auth, input validation, signature
# ---------------------------------------------------------------------------

CONTAINER_NO_RE = re.compile(r"^[A-Z0-9-]{1,15}$")
MAX_WEBHOOK_BODY_BYTES = 16 * 1024  # 16 KB hard cap


def _require_authenticated_user() -> None:
	"""Defence-in-depth: reject Guest even if ``allow_guest`` is ever flipped."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)


def _normalize_container_no(value) -> str:
	"""Uppercase and return the canonical container number. Required (and kept to a safe
	character set), but NOT length-checked — real depot data carries non-ISO / short
	numbers, so only presence is enforced."""
	if not value or not isinstance(value, str):
		frappe.throw(_("container_no is required."), frappe.ValidationError)
	candidate = value.strip().upper()
	if not CONTAINER_NO_RE.match(candidate):
		frappe.throw(_("Invalid container_no format."), frappe.ValidationError)
	return candidate


def _resolve_customer(value) -> str | None:
	"""Translate a Container.principal-ish string into a Customer ``name``.

	Accepts either an existing Customer name or a Customer's ``customer_name``.
	Returns ``None`` when no match — caller should leave the Link field blank
	rather than fail. (Auto-creating customers from gate-entry text is out of
	scope and would let typos pollute the master.)
	"""
	if not value or not isinstance(value, str):
		return None
	candidate = value.strip()
	if not candidate:
		return None
	if frappe.db.exists("Customer", candidate):
		return candidate
	return frappe.db.get_value("Customer", {"customer_name": candidate}, "name")


def _booking_customer(booking) -> str | None:
	"""Return the Customer (already a Link) behind an Container Booking, or None."""
	if not booking:
		return None
	return frappe.db.get_value("Container Booking", booking, "customer")


BOOKING_CODE_RE = re.compile(r"^OAK-[A-F0-9]{6,32}$")


def _parse_booking_code_payload(qr_data) -> str:
	"""Like :func:`_parse_qr_payload` but for Booking Code QR payloads.

	Accepts ``OAK|OAK-...`` (issued by Booking Code) or a bare ``OAK-...``.
	"""
	if not qr_data or not isinstance(qr_data, str):
		frappe.throw(_("qr_data is required."), frappe.ValidationError)
	raw = qr_data.strip()
	if raw.upper().startswith("OAK|"):
		parts = raw.split("|")
		if len(parts) < 2 or not parts[1]:
			frappe.throw(_("Malformed OAK QR payload."), frappe.ValidationError)
		raw = parts[1]
	candidate = raw.upper()
	if not BOOKING_CODE_RE.match(candidate):
		frappe.throw(_("Invalid Booking Code format."), frappe.ValidationError)
	return candidate


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
# Booking Code / QR Code Validation
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"], allow_guest=True)
@rate_limit(key="qr_data", limit=30, seconds=60)
def validate_qr(qr_data):
	"""Decode a Booking Code QR payload (``OAK|OAK-XYZ`` or bare ``OAK-XYZ``)
	and return its details. Read-only; safe to leave guest-accessible but
	rate-limited per IP to discourage enumeration.

	An ``Active`` Booking Code is the payment-cleared signal (a code is only
	issued after the Cash invoice is paid / TOP credit cleared).

	POST /api/v1/gate/validate-qr
	"""
	try:
		code = _parse_booking_code_payload(qr_data)
	except frappe.ValidationError as e:
		return {"valid": False, "error": str(e)}

	bc = frappe.db.get_value(
		"Booking Code",
		code,
		["name", "state", "direction", "container", "container_no", "booking", "expires_at"],
		as_dict=True,
	)
	if not bc:
		return {"valid": False, "error": "Booking Code not found"}

	return {
		"valid": bc.state == "Active",
		"booking_code": bc.name,
		"state": bc.state,
		"direction": bc.direction,
		"container": bc.container,
		"container_no": bc.container_no,
		"booking": bc.booking,
		"expires_at": str(bc.expires_at) if bc.expires_at else None,
	}


# ---------------------------------------------------------------------------
# Gate Entry Operations
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def register_gate_entry(booking_code, container_no, security_guard=None, truck_plate=None, driver_name=None):
	"""Log a container arrival at the gate against a Booking Code. Authenticated
	only.

	The Booking Code must be ``Active`` or ``Used`` — an Active code already
	encodes payment status, so no separate payment check is needed. The Gate
	Entry's own ``validate`` re-checks the code and the container match.

	POST /api/v1/gate/entry
	"""
	_require_authenticated_user()
	code = _parse_booking_code_payload(booking_code)
	container_no = _normalize_container_no(container_no)

	try:
		bc = frappe.db.get_value(
			"Booking Code",
			code,
			["name", "state", "container_no", "booking"],
			as_dict=True,
		)
		if not bc:
			return {"success": False, "error": "Booking Code not found"}
		if bc.state not in ("Active", "Used"):
			return {"success": False, "error": f"Booking Code state is {bc.state}; cannot pass the gate"}
		if bc.container_no and bc.container_no.upper() != container_no:
			return {"success": False, "error": f"Container {container_no} does not match Booking Code container {bc.container_no}"}

		container_name = frappe.db.get_value("Container", {"container_no": container_no})
		if not container_name:
			container = frappe.get_doc({
				"doctype": "Container",
				"container_no": container_no,
				"container_type": "ISO Tank",
				# Born pre-arrival; the Gate Entry submit below flips it to In_Depot
				# (setting In_Depot here would trip the gate-in "already present" guard).
				"status": "Booked",
				"principal": _booking_customer(bc.booking),
			})
			# TODO(Phase 6): drop ignore_permissions once the SST service role is
			# wired and the install.py blanket grant is replaced.
			container.insert(ignore_permissions=True)
			container_name = container.name

		gate_entry = frappe.get_doc({
			"doctype": "Gate Entry",
			"booking_code": bc.name,
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

		return {
			"success": True,
			"gate_entry_id": gate_entry.gate_entry_id,
			"container_no": container_no,
			"container_status": "In_Depot",
		}

	except frappe.ValidationError:
		raise
	except Exception as e:
		return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Pending Lifts (Reachstacker) — booking-code lookup for a container to lift.
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"], allow_guest=True)
@rate_limit(key="booking_code", limit=60, seconds=60)
def get_pending_lifts(booking_code=None, container_no=None):
	"""Get the container pending lift for a Booking Code. Read-only.

	GET /api/v1/yard/pending-lifts
	"""
	try:
		containers = []

		if booking_code:
			code = _parse_booking_code_payload(booking_code)
			bc = frappe.db.get_value(
				"Booking Code",
				code,
				["container_no", "container", "state"],
				as_dict=True,
			)
			if not bc:
				return {"success": False, "error": "Booking Code not found"}
			if bc.container_no:
				container_type = frappe.db.get_value("Container", bc.container, "container_type") if bc.container else "ISO Tank"
				containers.append({
					"container_no": bc.container_no,
					"status": bc.state,
					"container_type": container_type or "ISO Tank",
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
			})

		return {"success": True, "containers": containers}

	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
	except Exception as e:
		return {"success": False, "error": str(e)}


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


def generate_qr_code(code):
	"""Generate a base64 PNG QR for an OAK payload (``OAK|<code>``)."""
	import qrcode
	from io import BytesIO

	qr_data = f"OAK|{code}"
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
		"check_payment": ["payment", "paid", "booking", "code"],
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
	code_match = re.search(r"OAK-[A-F0-9]+", upper)
	container_match = re.search(r"([A-Z]{4}\d{6}-?\d)", upper)

	if not code_match:
		return "Please provide a booking code (e.g., OAK-ABC123) to proceed with gate-in."

	try:
		code = _parse_booking_code_payload(code_match.group(0))
	except frappe.ValidationError:
		return "Booking code format is invalid."

	bc = frappe.db.get_value("Booking Code", code, ["state"], as_dict=True)
	if not bc:
		return f"Booking code {code} not found. Please verify the booking code."
	if bc.state not in ("Active", "Used"):
		return f"⚠️ Booking code {code} state is {bc.state}. Please contact the office."

	if not container_match:
		return "Please provide the container number (e.g., STLU123456-7) that has arrived."

	try:
		container_no = _normalize_container_no(container_match.group(1))
	except frappe.ValidationError:
		return "Container number format is invalid."

	result = register_gate_entry(
		booking_code=code,
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
		"Please proceed to gate with the release booking code.\n"
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
	code_match = re.search(r"OAK-[A-F0-9]+", (message or "").upper())
	if not code_match:
		return "Please provide a booking code (e.g., OAK-ABC123) to check payment status."

	try:
		code = _parse_booking_code_payload(code_match.group(0))
	except frappe.ValidationError:
		return "Booking code format is invalid."

	bc = frappe.db.get_value(
		"Booking Code",
		code,
		["name", "state", "direction", "container_no", "booking", "expires_at"],
		as_dict=True,
	)
	if not bc:
		return f"Booking code {code} not found."

	customer = _booking_customer(bc.booking)
	response = f"*Booking Code: {bc.name}*\n"
	response += f"Direction: {(bc.direction or '').replace('_', ' ')}\n"
	response += f"Customer: {customer or 'N/A'}\n"
	response += f"Container: {bc.container_no or 'N/A'}\n"

	# An Active code is only issued after payment clears.
	if bc.state == "Active":
		response += "\n✅ Payment: VERIFIED\n\nYou may proceed with gate-in."
	elif bc.state == "Used":
		response += "\n✅ Payment: VERIFIED (code already used at the gate)."
	else:
		response += f"\n❌ Booking code state: {bc.state}\n\nPlease contact the office before gate-in."

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

	if doc.status == "Awaiting_MR_Approval":
		response += f"\n⚠️ Container awaiting M&R approval.\nLocation: {doc.current_location or 'Workshop'}\n"
	elif doc.status == "Repair_In_Progress":
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
   "Gate in STLU123456-7 with booking code OAK-ABC123"
   "Container arrived, booking code OAK-ABC123"

💰 *Check Payment*
   "Check payment for OAK-ABC123"
   "Is OAK-ABC123 paid?"

🧹 *Cleaning Queue*
   "Show cleaning queue"
   "What's in the cleaning bay?"

🔧 *Repair Status*
   "Repair status for STLU123456-7"

📸 *Upload Photos*
   "Upload inspection photo for STLU123456-7"

❓ *Help*
   "Help" or "What can you do?"

*Tip:* Always include container numbers (e.g., STLU123456-7) or booking codes (e.g., OAK-ABC123) in your messages.
"""


def handle_unknown(message, from_user, session_id):
	return """🤔 I'm not sure what you're asking for.

Please try one of these:
- "Check status of STLU123456-7"
- "Gate in with booking code OAK-ABC123"
- "Check payment for OAK-ABC123"
- "Show cleaning queue"
- "Help" for more commands
"""


# ---------------------------------------------------------------------------
# Agent Skills Definition (for Hermes/OpenClaw)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SST endpoints
# ---------------------------------------------------------------------------


def _resolve_sst_for_session() -> str | None:
	"""Return the Self Service Terminal whose api_user is the calling user."""
	user = frappe.session.user
	if not user or user == "Guest":
		return None
	return frappe.db.get_value("Self Service Terminal", {"api_user": user}, "name")


def _log_sst_activity(sst, action, *, booking_code=None, payload=None, result="OK"):
	if not sst:
		return
	try:
		frappe.get_doc({
			"doctype": "SST Activity Log",
			"sst": sst,
			"action": action,
			"booking_code": booking_code,
			"payload_json": json.dumps(payload, default=str) if payload else None,
			"result": result,
			"timestamp": now_datetime(),
		}).insert(ignore_permissions=True)
	except Exception:
		# Log write must never break the primary operation.
		frappe.log_error(frappe.get_traceback(), "container_depot SST log write failed")


@frappe.whitelist(methods=["POST"])
def sst_issue_order(qr_data, truck_plate=None, driver_name=None, driver_phone=None, transporter=None, ex_vessel=None, destination=None, cleaning_certificate=None):
	"""Validate a scanned Booking Code and issue the matching Order.

	The calling user must hold the ``Container Depot SST Service`` role and be
	linked as the ``api_user`` of a Self Service Terminal. Returns the new
	Order's name plus the QR payload to reprint if needed.
	"""
	_require_authenticated_user()
	sst = _resolve_sst_for_session()
	code = _parse_booking_code_payload(qr_data)
	bc = frappe.db.get_value(
		"Booking Code",
		code,
		["name", "state", "direction", "container", "container_no", "booking", "expires_at"],
		as_dict=True,
	)
	if not bc:
		_log_sst_activity(sst, "Code Scan", payload={"qr_data": qr_data}, result="Error")
		frappe.throw(_("Booking Code not found."))
	if bc.state != "Active":
		_log_sst_activity(sst, "Validate", booking_code=bc.name, payload={"state": bc.state}, result="Error")
		frappe.throw(_("Booking Code {0} state is {1}.").format(bc.name, bc.state))

	# Build vehicle data and delegate to the shared atomic core (handles the
	# row-lock, order creation, and flipping the code to Used). SST scans exactly
	# one code; the core accepts 1..3 so both entry points share one code path.
	vehicle_data = {
		"truck_plate": truck_plate,
		"driver_name": driver_name,
		"driver_phone": driver_phone,
		"transporter": transporter,
	}
	if bc.direction == "Tank In":
		vehicle_data["ex_vessel"] = ex_vessel
	else:
		if not cleaning_certificate:
			_log_sst_activity(sst, "Validate", booking_code=bc.name, payload={"missing": "cleaning_certificate"}, result="Error")
			frappe.throw(_("Cleaning Certificate is required to issue an Order Muat."))
		vehicle_data["destination"] = destination
		vehicle_data["cleaning_certificates"] = {bc.name: cleaning_certificate}

	from container_depot.operations.order_generation import make_order

	order_name = make_order(bc.booking, [bc.name], vehicle_data=vehicle_data, sst=sst, submit=True)
	order_doctype = "Order Bongkar" if bc.direction == "Tank In" else "Order Muat"
	_log_sst_activity(
		sst,
		"Order Issued",
		booking_code=bc.name,
		payload={"order": order_name, "doctype": order_doctype},
	)
	return {
		"success": True,
		"order_doctype": order_doctype,
		"order_name": order_name,
		"booking_code": bc.name,
		"qr_payload": f"OAK|{bc.name}",
	}


@frappe.whitelist()
def get_booking_pending_containers(booking):
	"""Containers on a booking still issuable onto a bon: Active Booking Codes.
	Drives the DMS 'Generate Bon / Order' dialog.

	Read-only; left unrestricted on HTTP method so the desk's ``frappe.call``
	(which POSTs by default) can reach it."""
	_require_authenticated_user()
	if not booking or not frappe.db.exists("Container Booking", booking):
		frappe.throw(_("Booking {0} not found.").format(booking))
	# Each pending container also carries its booking line's detail (condition / cargo /
	# truck / driver / R-O / Tgl. Bongkar / remarks) so the Generate dialog can auto-fill
	# the voucher from the first container picked.
	return frappe.db.sql(
		"""
		SELECT bc.name AS booking_code, bc.container, bc.container_no, bc.status_tag, bc.direction,
		       i.condition, i.cargo, i.truck_plate, i.driver, i.driver_phone, i.ro,
		       i.tanggal_bongkar, i.remarks
		FROM `tabBooking Code` bc
		LEFT JOIN `tabContainer Booking Item` i
		       ON i.parent = bc.booking AND i.container_no = bc.container_no
		WHERE bc.booking = %(booking)s AND bc.state = 'Active'
		ORDER BY bc.container_no
		""",
		{"booking": booking},
		as_dict=True,
	)


@frappe.whitelist(methods=["POST"])
def generate_order_from_booking(booking, selected_codes, vehicle_data=None):
	"""DMS desktop entry point: issue ONE bon (1..3 containers) from a booking.

	Thin wrapper over the shared atomic core so the SST and DMS paths can never
	drift apart.
	"""
	_require_authenticated_user()
	from container_depot.operations.order_generation import make_order

	vd = vehicle_data
	if isinstance(vd, str) and vd:
		vd = json.loads(vd)
	order_name = make_order(booking, selected_codes, vehicle_data=vd or {}, submit=True)
	direction = frappe.db.get_value("Container Booking", booking, "direction")
	return {
		"success": True,
		"order_doctype": "Order Bongkar" if direction == "Tank In" else "Order Muat",
		"order_name": order_name,
	}


# ---------------------------------------------------------------------------
# Gate PWA — scan/type a Booking Code or Order code → booking detail → per-container
# bon generation (max 2). Cash bookings must be Paid (pay at the cashier first).
# ---------------------------------------------------------------------------


def _parse_gate_code(code) -> str:
	"""Strip an optional ``OAK|`` QR prefix and upper-case. Accepts a Booking Code
	(``OAK-…``), an Order (``ORD-…``), or a Container Booking name."""
	if not code or not isinstance(code, str):
		frappe.throw(_("code is required."), frappe.ValidationError)
	raw = code.strip()
	if raw.upper().startswith("OAK|"):
		parts = raw.split("|", 1)
		raw = parts[1].strip() if len(parts) > 1 else ""
	return raw.upper()


def _resolve_booking_from_code(raw) -> str | None:
	"""Booking Code → its booking; Order Bongkar/Muat → its booking; or a Container
	Booking name directly."""
	if not raw:
		return None
	if frappe.db.exists("Booking Code", raw):
		return frappe.db.get_value("Booking Code", raw, "booking")
	if raw.startswith("ORD-BKR") and frappe.db.exists("Order Bongkar", raw):
		return frappe.db.get_value("Order Bongkar", raw, "booking")
	if raw.startswith("ORD-MT") and frappe.db.exists("Order Muat", raw):
		return frappe.db.get_value("Order Muat", raw, "booking")
	if frappe.db.exists("Container Booking", raw):
		return raw
	return None


def _find_order_for_code(code) -> dict | None:
	"""The non-voided Order (Bongkar/Muat) a Booking Code currently sits on, if any."""
	for child_dt, parent_dt in (
		("Container Booking Item", "Order Bongkar"),
		("Order Container Item", "Order Muat"),
	):
		for row in frappe.get_all(
			child_dt, filters={"booking_code": code, "parenttype": parent_dt}, fields=["parent"]
		):
			docstatus = frappe.db.get_value(parent_dt, row.parent, "docstatus")
			if docstatus in (0, 1):  # draft or submitted (a voided bon = docstatus 2 frees the code)
				return {"name": row.parent, "doctype": parent_dt, "docstatus": docstatus}
	return None


def _booking_gate_detail(booking) -> dict:
	"""Header + per-container bon status for the gate panel, plus the Cash-unpaid gate.

	Out-of-branch bookings are refused up front so a scoped gate user never sees a
	booking (and its container/payment data) belonging to another branch."""
	branch = frappe.db.get_value("Container Booking", booking, "branch")
	try:
		assert_in_user_branch(branch=branch)
	except frappe.PermissionError:
		return {"valid": False, "error": _("Booking ini di luar branch Anda.")}
	b = frappe.db.get_value(
		"Container Booking",
		booking,
		[
			"name", "branch", "depot", "booking_status", "docstatus", "direction", "customer", "principal",
			"lift_item", "payment_type", "payment_status", "sales_invoice", "do_reference", "remarks",
		],
		as_dict=True,
	)
	# Gate actions need a SUBMITTED (confirmed) booking. Until then the gate is blocked
	# with a reason the operator can act on: pay at the cashier (Cash unpaid) or contact
	# admin (paid/TOP but the booking isn't confirmed yet).
	booking_submitted = b.docstatus == 1
	payment_blocked = (b.payment_type == "Cash") and ((b.payment_status or "Unpaid") != "Paid")
	if booking_submitted:
		block_reason = None
	elif payment_blocked:
		block_reason = "cash_unpaid"
	else:
		block_reason = "not_submitted"
	containers = []
	for c in frappe.get_all(
		"Booking Code",
		filters={"booking": booking},
		fields=["name", "container", "container_no", "state", "direction"],
		order_by="container_no asc",
	):
		# Booking-line detail (truck/driver/voucher) so the gate form can auto-fill from
		# the first selected container — same source the Desk Generate dialog uses.
		line = frappe.db.get_value(
			"Container Booking Item",
			{"parent": booking, "container_no": c.container_no},
			["condition", "cargo", "truck_plate", "driver", "driver_phone", "ro", "tanggal_bongkar"],
			as_dict=True,
		) or {}
		containers.append({
			"booking_code": c.name,
			"container": c.container,
			"container_no": c.container_no,
			"code_state": c.state,
			"direction": c.direction,
			"order": _find_order_for_code(c.name),
			"line": line,
		})
	return {
		"booking": b.name,
		"branch": b.branch,
		"depot": b.depot,
		"booking_status": b.booking_status,
		"direction": b.direction,
		"customer": b.customer,
		"customer_name": frappe.db.get_value("Customer", b.customer, "customer_name") if b.customer else None,
		"principal": b.principal,
		"principal_name": frappe.db.get_value("Customer", b.principal, "customer_name") if b.principal else None,
		"lift_item": b.lift_item,
		"payment_type": b.payment_type,
		"payment_status": b.payment_status,
		"sales_invoice": b.sales_invoice,
		"do_reference": b.do_reference,
		"remarks": b.remarks,
		"booking_submitted": booking_submitted,
		"payment_blocked": payment_blocked,
		"block_reason": block_reason,
		"containers": containers,
	}


@frappe.whitelist(methods=["GET"])
def gate_cargo_options():
	"""Active Cargo names for the gate 'Generate Bon' form's cargo picker — mirrors the
	Desk dialog's Cargo Link so the operator chooses from the master, not free text."""
	_require_authenticated_user()
	return {"cargos": frappe.get_all("Cargo", filters={"is_active": 1}, pluck="name", order_by="name asc")}


@frappe.whitelist()
def gate_lookup(code):
	"""Gate PWA: resolve a scanned/typed code — Booking Code (``OAK-…``), Order
	Bongkar/Muat (``ORD-…``), or a Container Booking name — to its booking and return
	the gate detail (header + per-container bon status + Cash-unpaid block)."""
	_require_authenticated_user()
	raw = _parse_gate_code(code)
	booking = _resolve_booking_from_code(raw)
	if not booking:
		return {"valid": False, "error": _("Kode tidak ditemukan / tidak valid: {0}").format(raw)}
	return {"valid": True, **_booking_gate_detail(booking)}


def _latest_valid_cleaning_cert(container) -> str | None:
	"""The newest submitted, in-date Cleaning Certificate for a container (for Muat)."""
	from frappe.utils import getdate, today

	for r in frappe.get_all(
		"Cleaning Certificate",
		filters={"container": container, "docstatus": 1},
		fields=["name", "valid_until"],
		order_by="creation desc",
	):
		if not r.valid_until or getdate(r.valid_until) >= getdate(today()):
			return r.name
	return None


@frappe.whitelist(methods=["POST"])
def gate_generate_order(booking, selected_codes, vehicle_data=None):
	"""Gate PWA: issue a submitted bon for up to 2 of a booking's containers. Refuses
	when a Cash booking isn't Paid (pay at the cashier first).

	``vehicle_data`` (JSON string or dict) carries the truck/driver/voucher detail
	entered in the gate form — the same shape the Desk "Generate" dialog sends to
	``make_order`` (Tank In: ``truck_plate``/``driver``/``driver_phone``/``ro``/
	``condition``/``cargo``/``tanggal_bongkar_actual``/``shipper``/``ex_vessel``/
	``remarks``; Tank Out: ``truck_plate``/``driver_name``/``driver_phone``/``ro``/
	``angkutan``/``destination``/``tanggal_muat``/``shipper``/``remarks``). For Tank
	Out a valid Cleaning Certificate is auto-resolved per container."""
	_require_authenticated_user()
	b = frappe.db.get_value(
		"Container Booking", booking, ["payment_type", "payment_status", "direction", "docstatus"], as_dict=True
	)
	if not b:
		frappe.throw(_("Booking {0} not found.").format(booking))
	if (b.payment_type == "Cash") and ((b.payment_status or "Unpaid") != "Paid"):
		frappe.throw(_("Booking Cash belum dibayar — bayar ke kasir dulu sebelum generate bon."))
	if b.docstatus != 1:
		frappe.throw(_("Booking belum disubmit / dikonfirmasi — hubungi admin sebelum generate bon."))

	from container_depot.operations.order_generation import _as_code_list, make_order

	vd = vehicle_data
	if isinstance(vd, str):
		vd = json.loads(vd) if vd.strip() else {}
	vd = dict(vd) if isinstance(vd, dict) else {}  # copy; never mutate the caller's dict

	if b.direction == "Tank Out":
		certs = {}
		for code in _as_code_list(selected_codes):
			container = frappe.db.get_value("Booking Code", code, "container")
			cert = _latest_valid_cleaning_cert(container) if container else None
			if not cert:
				frappe.throw(
					_("Container {0} belum punya Cleaning Certificate valid untuk Order Muat.").format(
						container or code
					)
				)
			certs[code] = cert
		vd["cleaning_certificates"] = certs
		# Order Muat reads per-container remarks as a {code: text} dict — expand a single
		# form string to every selected container so it isn't silently dropped.
		if isinstance(vd.get("remarks"), str) and vd["remarks"].strip():
			vd["remarks"] = {code: vd["remarks"] for code in _as_code_list(selected_codes)}

	order_name = make_order(booking, selected_codes, vehicle_data=vd, submit=True)
	return {
		"success": True,
		"order_name": order_name,
		"order_doctype": "Order Bongkar" if b.direction == "Tank In" else "Order Muat",
	}


@frappe.whitelist(methods=["POST"])
def sst_heartbeat(printer_status="OK"):
	"""SST terminals call this every N minutes to update last_heartbeat."""
	_require_authenticated_user()
	sst = _resolve_sst_for_session()
	if not sst:
		frappe.throw(_("Calling user is not linked to a Self Service Terminal."))
	frappe.db.set_value(
		"Self Service Terminal",
		sst,
		{"printer_status": printer_status, "last_heartbeat": now_datetime()},
		update_modified=False,
	)
	_log_sst_activity(sst, "Heartbeat", payload={"printer_status": printer_status})
	return {"success": True, "sst": sst}


@frappe.whitelist(methods=["POST"])
def upload_inspection_offline_batch(items):
	"""Accept a JSON batch of EIR records collected offline by a SST/device.

	Each item: ``{client_uuid, container_no, inspection_type, inspector, photos}``.
	Deduped by ``client_uuid``. Items with bad shape are skipped, not 400'd.
	"""
	_require_authenticated_user()
	if isinstance(items, str):
		try:
			items = json.loads(items)
		except json.JSONDecodeError:
			frappe.throw(_("items must be a JSON array."), frappe.ValidationError)
	if not isinstance(items, list):
		frappe.throw(_("items must be a list."), frappe.ValidationError)

	created, skipped = [], []
	for raw in items:
		if not isinstance(raw, dict):
			continue
		client_uuid = raw.get("client_uuid")
		if not client_uuid:
			skipped.append({"reason": "missing client_uuid"})
			continue
		# Dedup: if any Inspection already has this uuid in its remarks, skip.
		if frappe.db.exists("Inspection", {"client_uuid": client_uuid}):
			skipped.append({"client_uuid": client_uuid, "reason": "already-ingested"})
			continue
		try:
			container_no = _normalize_container_no(raw.get("container_no"))
		except frappe.ValidationError as e:
			skipped.append({"client_uuid": client_uuid, "reason": str(e)})
			continue
		try:
			res = upload_inspection_evidence(
				container_no=container_no,
				photos=raw.get("photos") or [],
				inspection_type=raw.get("inspection_type") or "EIR-In",
				inspector=raw.get("inspector"),
			)
			if res.get("success"):
				# Tag with the client_uuid for idempotency.
				frappe.db.set_value(
					"Inspection", {"inspection_id": res["inspection_id"]}, "client_uuid", client_uuid
				)
				created.append({"client_uuid": client_uuid, "inspection_id": res["inspection_id"]})
			else:
				skipped.append({"client_uuid": client_uuid, "reason": res.get("error")})
		except Exception as e:
			skipped.append({"client_uuid": client_uuid, "reason": str(e)})

	return {"success": True, "created": created, "skipped": skipped}


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
			"description": "Decode a Booking Code QR and validate it. Returns booking code details including state (Active = payment cleared), direction, and container.",
			"parameters": ["qr_data"],
		},
		{
			"name": "register_gate_entry",
			"endpoint": "/api/v1/gate/entry",
			"method": "POST",
			"auth": "authenticated (SST service user)",
			"description": "Register container gate-in at security checkpoint against a Booking Code. Creates gate entry record and updates container status.",
			"parameters": ["booking_code", "container_no", "security_guard", "truck_plate", "driver_name"],
		},
		{
			"name": "get_pending_lifts",
			"endpoint": "/api/v1/yard/pending-lifts",
			"method": "GET",
			"auth": "guest (rate-limited)",
			"description": "Get the container pending lift for a Booking Code. Returns container number and status.",
			"parameters": ["booking_code", "container_no"],
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
