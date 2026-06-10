# PRD — Container Depot ESS / PWA

**Document ID:** PRD-ESS-001
**Version:** Draft 1.0 · 2 June 2026
**Target app:** `container_depot` (Frappe / ERPNext custom app)
**Primary users:** Field operations staff — Teknisi EIR & Foto, Operator Kalmar, Ops Supervisor, Staff Adm Ops, Security
**Status:** For review

> This is the machine-readable companion to `PRD_Container_Depot_ESS_PWA.docx`. It is the source of truth for scope. Every DocType, field, and endpoint named here is taken from the actual repository — verify against the live app before building.

---

## 1. Overview & Purpose

Build an **Employee Self-Service (ESS) Progressive Web App** as a mobile front-end on top of the existing `container_depot` app. Same two-surface model as ERPNext HRMS:

- **Desk** (`/app/...`) — stays the administrative back-office.
- **ESS PWA** (`/depot`) — phone-first, installable workspace for field staff, over the **same** DocTypes, controllers, and permission model.

**Key principle:** the PWA is a *consumer of the backend*, not a second system. All business logic (status transitions, EIR validation, repair costing) stays in the Python controllers already in the repo. The PWA calls the API; it never re-implements rules.

### Goals
- **Single source of truth** — replace per-principal Excel + paper EIR with data entered once, on the yard.
- **Field-first capture** — Teknisi EIR and Operator Kalmar record movements, EIR, photos, repairs from a phone, including offline.
- **Real-time visibility** — live tank inventory & status without compiling spreadsheets.
- **Auditable workflow** — digitise the PRO-OPS-009 isotank in/out SOP so each step has a timestamp + actor + document trail.

### Non-goals (this release)
- Customer/principal external portal (deferred).
- Billing / invoicing / SOA generation (stays in Desk → Accounts; ESS only reads status).
- Replacing the gate kiosk SST flow (ESS complements it).
- Native store apps (PWA install is the delivery mechanism).

---

## 2. Current System (already in `container_depot`) — REUSE, DON'T REBUILD

### 2.1 Relevant DocTypes (confirmed present)
Path: `container_depot/operations/doctype/`

| DocType | Purpose | ESS relevance |
|---|---|---|
| `Container` | Master tank/container; status lifecycle, `principal` (Customer Link), yard zone/row/bay/tier, cleaning & repair sub-status | Core read — inventory & status |
| `Container Movement` | Yard/status movement log: from/to zone & status, `moved_by`, timestamp | Written on lift / status change |
| `Gate Entry` | Gate in/out; booking code, truck, driver, EIR ref, inspection status | Written at gate; read for queue |
| `Inspection` | EIR-In/Out & survey; tank template fields, `exterior_photos`, `damage_log`, `repair_estimate`, `approval_status` | Primary EIR capture |
| `Damage Entry`, `Inspection Photo` | Child tables for damage lines & photo evidence | Captured with phone camera |
| `Repair Order`, `Repair Estimate Item` | Repair workflow, technician, costed lines, billing status | Repair tracking |
| `EIR Damage Code`, `EIR Repair Code` | Standardised code masters (hours, rate) | Pickers in EIR & repair |
| `Isotank Booking`, `Booking Code` | Booking + QR (Active/Used/Expired), direction Tank In/Out | Drives gate validation |
| `Order Bongkar`, `Order Muat` | Unload/load orders → map to Bon Bongkar / Bon Muat | Adm Ops issue/lookup |
| `Periodic Test` | 2.5Y / 5Y schedule, `due_date`, principal, billed-to | Due-test alerts |
| `Cleaning Order`, `Cleaning Certificate` | Cleaning workflow + certificate (has print format) | Cleaning queue & doc |
| `Depot` | Multi-depot master (code, city, active) | Depot scoping/filter |
| `Self Service Terminal`, `SST Activity Log` | Gate kiosk + audit log | **Out of ESS scope** |

### 2.2 Existing API surface (in `container_depot/api.py`, routed in `hooks.py`)
Reuse these — follow the same `/api/v1/...` convention and whitelisting style.

```
POST  /api/v1/gate/validate-qr            validate booking-code QR
POST  /api/v1/gate/entry                  register gate entry
GET   /api/v1/yard/pending-lifts          list containers awaiting lift
PATCH /api/v1/yard/update-location        update yard zone after lift
POST  /api/v1/inspection/upload-evidence  attach EIR photo evidence
POST  /api/v1/inspection/offline-batch    bulk-sync offline inspections
POST  /api/v1/sst/issue-order             (kiosk only)
POST  /api/v1/sst/heartbeat               (kiosk only)
```

An offline-batch endpoint and an authenticated-user guard (`_require_authenticated_user`) **already exist** — build offline-first on top of these.

---

## 3. Architecture

### 3.1 Two-surface model
```
Desk (/app/...)            ESS PWA (/depot)
  admin & back-office        field staff, mobile, installable
        \                         /
         \___ Frappe API (/api/v1, /api/resource) ___/
                        |
          Python controllers + hooks (single source of logic)
                        |
                   MariaDB (DocTypes)
```

### 3.2 Where code lives (SINGLE REPO — do not split)
```
container_depot/
  container_depot/operations/doctype/   # existing DocTypes (DO NOT change schema)
  container_depot/api.py                # existing + new ESS read endpoints
  container_depot/ess/                  # NEW: thin whitelisted ESS methods (optional)
  container_depot/www/depot.html        # NEW: mounts the Vue app at /depot
  container_depot/public/ess/           # NEW: Vite build output (served as asset)
frontend/                               # NEW: Vue 3 + frappe-ui source
  src/{pages,components}, src/router.js, src/main.js, public/manifest.json
```
Rationale for single repo: same reason Frappe HR ships its Vue app inside the `hrms` app — one business-logic source, one version, one deploy.

### 3.3 Technology
| Layer | Choice |
|---|---|
| Front-end | Vue 3 + `frappe-ui` (`createResource` / `createListResource`) — mirror Frappe HR |
| Build | Vite → output `container_depot/public/ess/` |
| Auth | Frappe session cookie; standard Frappe login; **no custom auth** |
| Offline | Service worker + IndexedDB queue; flush via `/api/v1/inspection/offline-batch` |
| Install | PWA manifest + service worker → Add to Home Screen |
| Permissions | Server-side Role + User Permission; PWA shows only what the role allows |

---

## 4. Users, Roles & Permissions (mapped to SOP PRO-OPS-009)

| Role | SOP responsibility | ESS capability |
|---|---|---|
| Teknisi EIR & Foto | Foto + tulis EIR saat tank in/out | Create/submit Inspection (EIR-In/Out), photos, damage log, draft estimate |
| Operator Kalmar | Cocokkan no. tank vs bon, susun per status | Pending lifts, confirm container vs booking, update yard location |
| Ops Supervisor | Approve cuci exterior, awasi alur | Dashboard, approve cleaning/repair, view all status |
| Staff Adm Ops | Terbitkan Bon Bongkar / Bon Muat | Issue/lookup Order Bongkar & Order Muat, link booking code |
| Security (gate) | Arahkan supir, tanda tangan bon | Validate QR/booking, confirm gate in/out, capture truck & driver |
| Depot Manager | Oversight | Read-only KPIs, all depots, periodic-test due, exceptions |

**Permission model:** depot-scoped via User Permission on `Depot`. No client-side permission logic — the server filters every list and document.

---

## 5. SOP Workflow (PRO-OPS-009) — each step writes to a DocType

### 5.1 Tank IN (Bongkar)
1. Security directs driver; Adm Ops issues Bon Bongkar → **Order Bongkar** created, booking code linked *(Adm Ops/Security)*
2. Driver reports to Operator Kalmar → **Gate Entry** status Active *(Security)*
3. Teknisi starts photos + writes EIR → **Inspection (EIR-In)**: tank template, photos, damage log *(Teknisi EIR)*
4. Kalmar matches tank no. vs Bon Bongkar → confirm container vs booking *(Operator Kalmar)*
5. Kalmar arranges per status; signs bon → `Container.status` set; **Container Movement** to yard zone *(Operator Kalmar)*
6. Security collects & signs white bon → Adm Ops → **Gate Entry** `Gate_In_Completed` *(Security/Adm Ops)*

### 5.2 Tank OUT (Muat)
1. Adm Ops issues Bon Muat; driver reports → **Order Muat** created *(Adm Ops)*
2. Teknisi re-checks exterior + EIR-Out → **Inspection (EIR-Out)** *(Teknisi EIR)*
3. If exterior dirty → notify Ops SPV → **Cleaning Order** raised; SPV approves *(Teknisi → Ops SPV)*
4. Teknisi applies "ready for release" sticker → `Container.status = Available` *(Teknisi EIR)*
5. Kalmar matches tank no. vs Bon Muat; signs → confirm + **Gate Entry** `Gate_Out_Completed` *(Operator Kalmar)*

---

## 6. Functional Requirements (build in priority order)

### F1 — Tank Inventory & Live Status — **MUST (Phase 1)**
Phone-first list of all tanks with live derived status + filtering by principal, status, yard zone, depot. Replaces per-principal Excel daily reports (Stolt, Nichicon, Bertschi, NCS) and KIM-11 inventory.

**User stories**
- As Ops Supervisor, I see counts by status (In Depot, Cleaning, Repair & Survey, Ready, Gate Out).
- As field staff, I filter by principal and search by tank number.
- As staff, I open a tank to see type, capacity, tare, last cargo, last test date, yard location, status.
- As Ops Supervisor, I see tanks with a periodic test due (2.5Y / 5Y) flagged.

**Acceptance criteria**
- Status is **derived server-side** (latest Container Movement + open Repair/Cleaning/Inspection), never free-typed in UI.
- List is **depot-scoped by User Permission**, paginated + searched **server-side**.
- Counts reconcile with REPORT_STORAGE_DEPO + KIM-11 categories (In Depot / Dirty / Clean / Repair / Cleaning).
- Usable data < 2s on 4G for a 1,000-tank depot (progressive render).

### F2 — Document Access & Download — **SHOULD (Phase 2)**
From a tank or order, view/download EIR (PDF), Bon Bongkar/Muat, repair estimate, cleaning certificate, storage/invoice references — from attachments + print formats already produced in Desk.
- Fetch via Frappe File / print-format endpoints respecting permissions (no direct FS access).
- Cleaning Certificate print format (exists in app) downloadable from the tank.
- Large PDFs stream without freezing; failures show retry.

### F3 — Repair Tracking & Estimate — **SHOULD (Phase 2/3)**
Damage logged in EIR → Repair Estimate (using EIR Repair Codes std hours/rate) → approval → in-progress → completed.
- Estimate total computed **server-side** from Repair Estimate Item lines; PWA never recomputes authoritative totals.
- Approval writes `Inspection.approval_status` / `Repair Order.status`, auditable.
- Billing status (Unbilled / Client Billed / Principal Billed) read-only in ESS.

### F4 — Gate Booking / Order Request — **COULD (Phase 3/4)**
Scan/enter booking-code QR, confirm container vs booking, capture truck & driver, complete gate-in/out — reusing `validate-qr` + `gate/entry`.
- QR validation calls existing `/api/v1/gate/validate-qr`; honours Booking Code state.
- Gate completion sets Gate Entry status + timestamps + actor.
- Mismatched tank vs booking is blocked with a clear message; nothing written.

---

## 7. Non-Functional Requirements

| Area | Requirement |
|---|---|
| Offline-first | EIR & photo capture works with no signal; queue in IndexedDB; sync via `/api/v1/inspection/offline-batch`; conflict = last-write-wins with audit |
| Performance | First meaningful paint < 2.5s on mid Android/4G; virtualised lists; client-side image compression before upload |
| Installability | Valid manifest + service worker; passes Lighthouse "installable" |
| Security | Reuse Frappe session; reject Guest (guard exists); all writes permission-checked server-side; HTTPS only |
| Auditability | Every status change writes actor + timestamp (Container Movement / Gate Entry) |
| Device | Camera for photos; 5–6" screens; one-handed primary actions; large tap targets |
| Localisation | Bahasa Indonesia primary labels (Bongkar, Muat, EIR), English fallback |
| Reliability | Graceful endpoint-failure handling; no silent data loss; visible sync state |

---

## 8. Data Mapping — retire the spreadsheets

| Current artifact | Fields | ESS source |
|---|---|---|
| KIM-11 Tank Inventory (Stolt/Nichicon/Bertschi) | stock in depot, dirty/clean, total in/out, cleaned, PT2.5/PT5, PP/methanol wash | `Container.status` + Cleaning Order + Periodic Test aggregates |
| Daily Report STOLT / NCS | tank no, last/next test, ex-cargo, in-depot date, remarks | Container + Inspection + Periodic Test |
| REPORT_STORAGE_DEPO_OAK | isotank/container, size, status, tare, max gross, capacity, last cargo, PL bongkaran, depot in/out | Container master + movement history |
| EIR (Eir_new_Rev_3) | prefix/number, vessel, in/out date, serial, damage/repair codes, tank status, dates, capacity, tare, MGW, last cargo | Inspection + Damage Entry + EIR Damage/Repair Code |
| Bon Bongkar / Bon Muat (MDN) | booking, container, truck, driver, vessel/destination | Order Bongkar / Order Muat |
| Estimate Repair (BGBU…) | damage/repair lines, hours, rate, total | Repair Order + Repair Estimate Item |
| Storage / SOA invoice (Bertschi) | storage days, charges | read-only status; billing stays in Accounts |

**Gap check:** Phase 1 needs only a couple of aggregate read endpoints (status counts, periodic-test-due). **No new core DocType required.**

---

## 9. Delivery Phases

| Phase | Scope | Outcome | Depends |
|---|---|---|---|
| 0 | Scaffold `frontend/` (Vite+frappe-ui), `/depot` route, session auth, PWA shell | Empty installable app, login works | — |
| 1 | F1 inventory & live status (read-only) + status-count endpoint | Retire daily Excel viewing | 0 |
| 2 | F2 documents + F3 repair view; EIR capture (read+create) | Digital EIR + doc access | 1 |
| 3 | F3 repair approval, F4 gate validate + gate-in/out | SOP in/out fully digital | 2 |
| 4 | Offline sync hardening, dashboards, periodic-test alerts | Resilient field ops | 3 |

**Build first:** Phase 0 + F1 together — validates the whole pipeline (auth → API → permission → render) end-to-end before deeper features.

---

## 10. Risks & Open Questions (resolve before/at Phase 0 sign-off)

| Risk / question | Mitigation / decision needed |
|---|---|
| `Container.status` Select has a **duplicated `In_Workshop`** value and 15 overlapping states | Audit & normalise options; define the canonical state machine before F1 |
| `permissions` arrays are **empty** in several DocType JSONs | Define + apply Role Permissions for all ESS roles before exposing PWA |
| Offline photo volume on poor connectivity | Client-side compression + chunked batch upload; cap queue with backpressure |
| Principal nuances (NCS demurrage, Bertschi storage) | Confirm operational vs billing fields; keep billing in Desk |
| Which roles/users exist in production? | Confirm role list + depot scoping before Phase 0 sign-off |
| iOS PWA limits (camera, background sync) | Validate on target iPhones early; fallback to foreground sync |

---

## Appendix — Glossary
- **EIR** — Equipment Interchange Receipt; condition record at gate in/out (DocType: `Inspection`)
- **Bon Bongkar / Bon Muat** — unload/load slip (DocTypes: `Order Bongkar` / `Order Muat`)
- **Operator Kalmar** — reach-stacker operator positioning tanks in the yard
- **Periodic Test (2.5Y/5Y)** — mandatory tank pressure/integrity test cycle
- **Principal** — tank-owning client (Stolt, Nichicon, Bertschi, NCS); `Container.principal` → Customer
- **PWA / ESS** — Progressive Web App / Employee Self-Service field surface