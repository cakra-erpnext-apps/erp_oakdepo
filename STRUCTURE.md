# ERPOakDepo Structure Rules

This repository is OakDepo stack/bundle repository. It follows same production pattern as `cakra-erpnext-apps/erp_cakra`.

## Repository contract

- Repository name: `erp_oakdepo`
- Docker compose project: `erp_oakdepo_prod`
- Frappe app package: `container_depot`
- Production site: configured by `SITE_NAME` in `.env.prod`

Repo name and Frappe app name may differ. Do not rename `container_depot` package without planned migration.

## Top-level layout

```text
.
├── compose.prod.yaml
├── .env.prod.example
├── Caddyfile
├── ensure-apps.sh
├── nginx-inject.sh
├── container_depot/
├── frontend/
├── docs/
├── README.md
└── STRUCTURE.md
```

## Code rules

1. Keep Frappe/ERPNext/CRM core untouched.
2. All custom backend code lives under `container_depot/`.
3. DocTypes live under `container_depot/<module>/doctype/<doctype>/`.
4. Hooks register in `container_depot/hooks.py`.
5. Data changes use fixtures, patches, or install hooks. No manual DB-only source of truth.
6. Production migrations must be repeatable and idempotent.
7. Tests go under `container_depot/tests/`.
8. Root scripts are stack-level only; app logic stays in Python app code.
9. Secrets stay in `.env.prod` or server secret store; never commit secrets.
10. Deploy through git then stack update. No live container edits as permanent fix.

## Split-stack rule

OakDepo runs in its own stack, separate from Cakra/Oakglobal stack.

- OakDepo repo/stack: `erp_oakdepo`
- Cakra/Oakglobal repo/stack: `erp_cakra`
- Do not share MariaDB volumes between stacks unless intentionally designed and documented.
- Do not install OakDepo app into Cakra/Oakglobal sites.
