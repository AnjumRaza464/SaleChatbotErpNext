# Role-based ERPNext AI Chatbot: Technical Implementation Plan

Goal: upgrade the existing single-chat assistant into four role-scoped tabs (Sales, Warehouse,
Stock, HR) with an administrator who assigns modules to users. Permissions are enforced on the
backend for chat, tools, exports, attachments and history. The ERPNext credentials stay on the server.

Current stack (audit, step 1 of the proposal):

| Layer | Today |
| --- | --- |
| Frontend | Next.js 16, React 19, Tailwind v4, shadcn/ui. One chat, no login. |
| Backend | FastAPI. Routes: chat (SSE), conversations, uploads, export, transcribe, health. No auth. |
| AI | OpenAI tool calling (`gpt-4o-mini`), topic guard, 44 read-only tools in 9 modules + file tools. |
| ERPNext | One server-side API key/secret via `httpx`; `frappe.desk.reportview.get` and query reports. |
| Storage | SQLite: conversations, messages, uploads, datasets. No owner column. |

Everything below extends this; nothing is rebuilt.

---

## 1. Data model (SQLite, `backend/app/storage/db.py`)

New tables:

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,          -- bcrypt
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE user_modules (               -- which tabs a user may open
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module TEXT NOT NULL CHECK (module IN ('sales','warehouse','stock','hr')),
    PRIMARY KEY (user_id, module)
);
CREATE TABLE audit_log (                  -- every chat/export, HR flagged
    id TEXT PRIMARY KEY, user_id TEXT, module TEXT, action TEXT, detail TEXT, created_at TEXT
);
```

Existing tables get owner/scope columns (migration adds them with `ALTER TABLE ... ADD COLUMN`):

- `conversations`: `user_id TEXT`, `module TEXT`
- `uploads`: `user_id TEXT`
- `datasets`: inherit scope through `message_id -> conversation` (no change needed, but the
  export route must join to check the owner).

Admin bootstrap: on first start, if no admin exists, create one from `ADMIN_EMAIL` /
`ADMIN_PASSWORD` in `.env`. The admin can create further users from the UI.

Permission matrix (default, editable per user):

| Role template | Sales | Warehouse | Stock | HR |
| --- | :-: | :-: | :-: | :-: |
| Sales User | x | | | |
| Warehouse User | | x | | |
| Stock User | | | x | |
| HR User | | | | x |
| Administrator | x | x | x | x |

A user can hold any combination of modules; "Administrator" additionally manages users.

## 2. Authentication (`backend/app/auth/`)

- `POST /api/auth/login` (email + password) -> sets an `HttpOnly`, `SameSite=Lax` session cookie
  containing a signed JWT (`SESSION_SECRET` in `.env`, 12 h expiry). `POST /api/auth/logout`,
  `GET /api/auth/me` (returns name, is_admin, modules).
- FastAPI dependencies:
  - `current_user()` -> 401 if no valid cookie or user inactive.
  - `require_module(module)` -> 403 unless `module in user.modules` or `user.is_admin`.
  - `require_admin()`.
- Passwords hashed with `bcrypt` (add `passlib[bcrypt]` or `bcrypt` to `requirements.txt`);
  JWT with `PyJWT`.
- Rate-limit login attempts (simple in-memory counter per email/IP, 10 per 15 min).
- Because the Next.js rewrite proxies `/api/*`, the cookie is same-origin; no CORS changes.

## 3. Module -> tool scoping (the core of enforcement)

A new file `backend/app/agent/modules.py` defines what each tab may touch. The registry already
tags every tool with its source file (`tool.module`), so scoping is a mapping on top of it.

```python
MODULE_TOOLS = {
  "sales":     {"sales", "pos", "parties", "accounts_receivable"},   # tool-file names
  "warehouse": {"stock_movement", "purchase_receipts"},
  "stock":     {"stock_balance", "items"},
  "hr":        {"hr"},
}
MODULE_DOCTYPES = {   # allowlist for the generic tools (query_doctype, get_document, count_records, reports)
  "sales":     {"Sales Invoice", "POS Invoice", "Sales Order", "Quotation", "Delivery Note", "Customer",
                "Customer Group", "Territory", "Payment Entry", "Pricing Rule", "Item Price", "POS Profile", "Cost Center"},
  "warehouse": {"Stock Entry", "Material Request", "Purchase Receipt", "Delivery Note", "Warehouse",
                "Stock Ledger Entry", "Pick List", "Packing Slip"},
  "stock":     {"Item", "Item Group", "Bin", "Warehouse", "Stock Ledger Entry", "Stock Reconciliation",
                "Batch", "Serial No", "Item Price", "Brand", "UOM"},
  "hr":        {"Employee", "Department", "Designation", "Attendance", "Leave Application", "Leave Allocation",
                "Holiday List", "Shift Assignment", "Employee Checkin", "Salary Slip", "Salary Structure Assignment"},
}
MODULE_REPORTS = {...}   # allowed query report names per module
```

Concrete code changes:

1. **Split two existing module files** so the tab boundaries are clean (handlers move, no logic
   changes): `stock.py` -> `stock_balance.py` (balances, low stock, items, item details) and
   `stock_movement.py` (stock entries, ledger, movement summary); `accounts.py` ->
   `accounts_receivable.py` (outstanding invoices, party outstanding, payment entries) and
   `accounts_gl.py` (P&L, GL, balances, journals; admin only). New `hr.py` with dedicated tools:
   `get_employee_list`, `get_attendance_summary`, `get_leave_balance`, `list_leave_applications`,
   `get_salary_register` (salary tools additionally require the user to hold HR; amounts are never
   exposed to other modules).
2. `ToolRegistry.openai_schemas(module)` and `ToolRegistry.call(name, ..., module)` take the active
   module. The model only ever sees the allowed tools, and `call` raises 403 for anything else even
   if the model names it. The generic tools receive the module's doctype allowlist through a
   `ToolContext` object instead of the global `BLOCKED_DOCTYPES` check alone.
3. `run_agent(message, history, attachments, module, user)` builds a module-specific system prompt
   (`prompts.py` gains `MODULE_PROMPTS[module]`: scope description, example questions, and the
   refusal rule "If the question belongs to another area (e.g. HR attendance asked in Sales), reply:
   'This belongs to the <X> module. You do not have access to it in this tab.'").
4. The topic guard gets the module too, so an HR question in the Sales tab is classified
   `erpnext_related: true, in_scope: false` and refused before any tool runs. The guard is still
   advisory; the registry restriction is what actually prevents data access.
5. `files/tools.py` (uploaded file analysis) stays available in every module since it only reads
   the user's own upload; uploads are owner-checked.

## 4. Backend routes

| Route | Change |
| --- | --- |
| `POST /api/chat` | body gains `module`; `require_module(module)`; conversation must belong to user and module. |
| `GET/POST/PATCH/DELETE /api/conversations` | filtered by `user_id` and `?module=`; cross-user access -> 404. |
| `POST /api/uploads` | stores `user_id`; attachment ids in chat must belong to the same user. |
| `GET /api/export/...` | join dataset -> message -> conversation; owner and module checked; HR export written to `audit_log`. |
| `POST /api/transcribe` | `current_user` only. |
| `GET /api/health` | public but without tool/module detail unless admin. |
| `/api/admin/users` (new) | admin CRUD: create user, set modules, activate/deactivate, reset password. |

All checks use the dependency chain, so hiding a tab in the UI is never the only barrier.

## 5. Frontend

- `src/app/login/page.tsx`: email/password form; on success `router.push('/')`.
- `src/middleware.ts`: redirect to `/login` when the session cookie is missing.
- `src/app/page.tsx`: fetch `/api/auth/me`; render a tab bar with only the user's modules (Sales,
  Warehouse, Stock, HR), each with its own colour, icon and empty-state suggestions. The active
  module is held in the URL (`/?tab=sales`) so refresh keeps it.
- `use-chat.ts`: keyed by module. Conversation list, search and new-chat all pass `module`;
  switching tabs swaps the list and clears the composer.
- Sidebar header shows user name, role chips and Logout; admin sees a "Users" entry opening
  `src/app/admin/page.tsx` (table of users, module checkboxes, create/disable).
- Composer placeholder and suggestion chips come from a per-module config in `src/lib/modules.ts`.

## 6. HR specific protection

- Salary and bank fields (`Salary Slip`, `Employee.bank_ac_no`, `salary_mode`, `ctc`) are returned
  only by the dedicated HR tools, never through `query_doctype`, and only when the user holds HR.
- HR responses are not cached in the site context; every HR chat and export is written to
  `audit_log` with user, question and tool names.
- Transcripts of HR conversations are deleted with the user when an admin deactivates them
  (optional retention switch).

Note for this site: there are currently no `Employee` records and the HRMS app is not installed,
so the HR tab will answer "no records found" until HRMS is installed and populated. The tab can
still be built and tested with the permission tests below.

## 7. Security tests (`backend/tests/`, pytest + httpx `ASGITransport`)

1. Anonymous `POST /api/chat` -> 401.
2. Sales user, `module=hr` -> 403 before the agent runs.
3. Sales user, `module=sales`, question "Show employee attendance" -> refusal text; tool log
   contains no HR tool; `query_doctype("Attendance")` raises 403 even when invoked directly through
   the registry with `module="sales"`.
4. Export of a dataset from another user's conversation -> 404.
5. Attachment id of another user passed in `attachment_ids` -> 403.
6. Admin can list all modules; deactivated user's cookie -> 401.
7. Registry snapshot test: for each module, the exposed tool names equal the expected allowlist
   (catches accidental leaks when someone adds a tool file).

## 8. Delivery order and estimates

| Step | Work | Size |
| --- | --- | --- |
| 1 | DB migration, users/admin bootstrap, auth routes, dependencies, login page, middleware | 1 day |
| 2 | Module map, registry scoping, generic-tool allowlists, module prompts, guard scope | 1 day |
| 3 | Split stock/accounts files, new HR tools | 0.5 day |
| 4 | Conversation/upload/export ownership + module filter | 0.5 day |
| 5 | Tab bar, per-module chat state, admin users page | 1 day |
| 6 | Security tests, audit log, README update, deploy env vars (`SESSION_SECRET`, `ADMIN_*`) | 0.5 day |

Total about 4.5 working days. Steps 1-2 are the security core and should land first; the UI tabs
(step 5) can be demoed as soon as step 2 exists.

## 9. Decisions to confirm

1. **Where do users live?** This plan uses local users in the app's SQLite with an admin page.
   Alternative: log in with ERPNext credentials and let ERPNext roles decide (strongest, but every
   chatbot user then needs an ERPNext user and API access).
2. **Should Sales also see Accounts Receivable** (customer outstanding)? Included above; remove
   `accounts_receivable` from `MODULE_TOOLS["sales"]` if not.
3. **Multi-module users**: allowed by design (checkbox per module).
4. **HR salary data**: shown to HR users only, or to admin only? Plan says HR users.
