# ERPNext AI Assistant

A ChatGPT/Claude-style assistant that answers questions **only about ERPNext** using
**live data** from your cloud-hosted ERPNext instance. It supports file analysis
(Excel, CSV, PDF, DOCX, TXT) and one-click **Export to Excel** of any query result.

```
User → Chat UI (Next.js) → FastAPI backend → AI agent (OpenAI tool calling)
     → ERPNext service layer (modules) → ERPNext REST API → live data
```

## Project layout

```
backend/.env              # your credentials (never committed, never sent to the browser)
backend/                  # FastAPI + AI agent + ERPNext service layer
  app/
    main.py               # app factory, CORS, error handlers, lifespan
    core/                 # settings (.env), logging, error types
    api/routes/           # health, conversations, chat (SSE), uploads, export
    agent/                # prompts, ERPNext-only guard, tool-calling loop
    services/erpnext/
      client.py           # async REST client (reportview / resource / reports)
      context.py          # cached site facts (company, currency, timezone)
      registry.py         # auto-discovers modules and exposes their tools
      modules/            # sales, accounts, stock, purchase, parties, pos,
                          # manufacturing, organization, generic
    files/                # parsers (xlsx/xls/csv/pdf/docx/txt) + analysis tool
    export/excel.py       # openpyxl workbook builder (headers, filters, totals…)
    storage/db.py         # SQLite: conversations, messages, uploads, datasets
  data/                   # runtime data (SQLite DB, uploads) – git-ignored
frontend/                 # Next.js 16 + TypeScript + Tailwind v4 + shadcn/ui
  src/app                 # layout / page
  src/components/chat     # sidebar, chat view, composer, message bubble, markdown
  src/hooks/use-chat.ts   # chat state + SSE streaming
  src/lib/api.ts          # API client (talks to /api, proxied to the backend)
docs/PLAN.md              # implementation plan and findings
```

## Configuration

Credentials go in `backend/.env` (the project-root `.env` is also read, if present).
The file is git-ignored and never sent to the browser.

```
# ERPNext
ERPNEXT_BASE_URL=https://your-site.erpnext.com   # ERPNEXT_URL also accepted
ERPNEXT_API_KEY=...
ERPNEXT_API_SECRET=...

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
# OPENAI_GUARD_MODEL=gpt-4o-mini

# App (optional)
CORS_ORIGINS=http://localhost:3001
MAX_UPLOAD_MB=20
MAX_TOOL_ROWS=500
MAX_AGENT_ITERATIONS=8
LOG_LEVEL=INFO
```

The frontend reads `BACKEND_URL` (default `http://127.0.0.1:8000`) from
`frontend/.env.local`. Only set it if the backend runs on another host/port.

## Requirements

- Python 3.11+ (tested with 3.14)
- Node.js 20+
- Access to a cloud-hosted ERPNext site with an API key/secret
- An OpenAI API key

## Run (step by step)

Open PowerShell in the project root (`E:\Sales_chatbot_ERPNext_Final`).

### 1. Backend (first time only: create venv + install)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Backend (every time)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

If PowerShell blocks `Activate.ps1` ("running scripts is disabled"), either run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activation and use:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

A healthy startup log looks like:

```
INFO app.services.erpnext.registry: Loaded 39 ERPNext tools from 9 modules
INFO app.main: Connected to ERPNext 15.x (company=..., currency=PKR, tz=Asia/Karachi)
INFO: Uvicorn running on http://127.0.0.1:8000
```

Health check: open `http://127.0.0.1:8000/api/health` in a browser. It shows the ERPNext
connection, company, currency and the loaded tools/modules.

### 3. Frontend (new PowerShell window)

```powershell
cd frontend
npm install                     # first time only
npm run dev -- --port 3001      # http://localhost:3001
```

### One-shot alternative

From the project root, `.\start.ps1` creates the venv / installs `node_modules` if missing
and opens the backend and frontend in two separate windows.

## Troubleshooting

**`Fatal error in launcher: Unable to create process using '...\python.exe'`**

The venv was created in a different folder path than where it lives now (for example the
project was moved or renamed). The `.exe` launchers inside `.venv\Scripts` (uvicorn.exe,
pip.exe) have the old absolute path baked in. You can confirm by looking at the `command =`
line in `backend\.venv\pyvenv.cfg`. Fix: delete the venv and recreate it in place.

```powershell
cd backend
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Do this again any time the project folder is moved.

**`python` is not recognized / wrong Python version**

Use the full path to the interpreter when creating the venv, e.g.
`C:\Users\<you>\AppData\Local\Programs\Python\Python314\python.exe -m venv .venv`.

**`ERPNext site context not loaded` warning at startup**

The backend started but could not reach ERPNext. Check `ERPNEXT_BASE_URL`,
`ERPNEXT_API_KEY` and `ERPNEXT_API_SECRET` in `backend/.env`, then restart.

**Port 8000 or 3001 already in use**

Pick another port with `--port` (backend) or `-- --port` (frontend). If you change the
backend port, set `BACKEND_URL` in `frontend/.env.local` and `CORS_ORIGINS` in
`backend/.env` accordingly.

## Features

- **Live ERPNext data** for Sales, Accounts, Stock/Inventory, Purchase, Customers,
  Suppliers, POS, Manufacturing, Branches, Departments, Employees and any other doctype
  (through the generic read-only query tool and standard ERPNext reports).
- **Strict ERPNext-only rule**: unrelated questions get exactly
  *"Sorry, I don't know. Kindly ask me an ERPNext-related question."*
- **Answer rules**: max 10 lines, tables/bullets, never invents data, resolves relative
  dates (today / yesterday / this month / last month) in the site timezone.
- **Attachments**: Excel/CSV are profiled and analysed with pandas (exact group-bys,
  sums, top-N, filters); PDF/DOCX/TXT are read as text.
- **Export to Excel**: every assistant message with tabular results has an
  *Export to Excel* button producing a formatted `.xlsx` (title, styled headers,
  auto filter, frozen header, currency/date formats, SUBTOTAL totals row, auto widths,
  plus a Summary sheet with KPIs).
- **UI**: sidebar with new chat, searchable history (title + message text), rename and
  delete, streaming responses with progress status, copy response, retry on error,
  drag-and-drop attachments, light/dark theme, mobile drawer sidebar.

## Adding an ERPNext module

Create `backend/app/services/erpnext/modules/<name>.py` that defines `TOOLS: list[Tool]`.
Each `Tool` has a name, description, JSON-schema parameters and an async handler
`(client, **params) -> ToolResult`. The registry picks it up automatically at startup
and the AI agent can use it immediately. See `modules/pos.py` for a compact example.

## Notes on this ERPNext site

- POS invoices are consolidated into Sales Invoices at day close, so sales totals use
  *POS Invoices + non-consolidated Sales Invoices* to avoid double counting.
- No `Branch` records exist; branch-wise figures use cost center / POS profile / warehouse.
- Sales invoices carry no department field; the assistant says so and offers
  cost-center / warehouse / item-group breakdowns instead.
