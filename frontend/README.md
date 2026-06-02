# Container Depot — ESS PWA (`frontend/`)

Vue 3 + [`frappe-ui`](https://frappeui.com) Progressive Web App for field
operations staff. It is a **consumer of the existing `container_depot` backend**
— all business logic (status derivation, EIR validation, costing) lives in the
Python controllers; the PWA only calls the API. Structure mirrors the
`hrms/frontend` app.

The app is served by Frappe at **`/depot`** (see
[`container_depot/www/depot.py`](../container_depot/www/depot.py)).

## Layout

```
frontend/
  src/
    main.js            # app bootstrap + service-worker registration
    App.vue            # shell (header + <router-view>)
    router.js          # /(Home) /tanks /tanks/:name, history base /depot
    service-worker.js  # minimal app-shell SW (installability)
    data/              # session (cookie auth) + frappe-ui resources
    pages/             # Home, TankInventory, TankDetail
    utils/labels.js    # Indonesian-primary labels (English fallback)
  public/
    manifest.json      # PWA manifest
    icons/             # 192 + 512 PNG icons
```

## Develop (`vite dev`, proxied to the bench)

```bash
cd frontend
yarn install            # first time only
yarn dev                # http://localhost:8081
```

`vite.config.js` walks up to the `frappe-bench` directory and reads
`sites/common_site_config.json` to find the bench webserver port, proxying
`/app /login /api /assets /files /private` to it (defaults to `:8000` if not
found — e.g. when the bench runs in a separate container).

- **Auth in dev:** log in to the bench in the same browser first; the
  `user_id` / session cookies are reused over the proxy. The dev boot context is
  fetched from `container_depot.www.depot.get_context_for_dev` (developer mode
  only). Open the app at `http://localhost:8081/depot`.

## Build (output → `container_depot/public/ess/`)

```bash
cd frontend
yarn build
```

`build` runs `vite build --base=/assets/container_depot/ess/` then
`copy-html-entry`, which copies the built `index.html` to
`container_depot/www/depot.html`. Frappe then serves the app at **`/depot`**,
with assets under `/assets/container_depot/ess/`.

> The build output (`container_depot/public/ess/`) and the generated
> `container_depot/www/depot.html` are build artifacts and are git-ignored.
> Run `yarn build` (or `bench build`) on deploy.

## Backend notes & known risks (PRD §10)

These are surfaced here so they are not silently worked around:

1. **`Container.status` has a duplicated `In_Workshop`** option (and ~15
   overlapping raw states). The PWA never trusts the raw `status`; the ESS
   endpoints derive a **canonical 5-bucket status** server-side
   (In Depot / Cleaning / Repair & Survey / Ready / Gate Out) from the latest
   Container Movement + open Repair/Cleaning/Inspection. Normalising the
   underlying Select is tracked as separate backend tech-debt.

2. **DocType JSON `permissions` arrays are empty** — this is **intentional**:
   permissions are seeded as **Custom DocPerm** by `container_depot/install.py`
   (`setup_permissions`, run on install + every migrate). The ESS endpoints use
   permission-aware queries (`frappe.get_list` / `frappe.get_doc`), so the PWA
   shows exactly what each role's DocPerms allow. No permission logic in the UI.

3. **Depot scoping** relies on a `User Permission (allow=Depot)` per user.
   `Container.depot` is a Link to `Depot`, so this filters automatically through
   `frappe.get_list`. Assigning those User Permissions is an ops prerequisite —
   `install.py` only auto-creates Customer-scoped permissions today.
