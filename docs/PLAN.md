# ERPNext AI Assistant – Implementation Plan

## Findings from project inspection (2026-09-26)

- The project folder contained only `.env` (ERPNext URL/key/secret + OpenAI key, model `gpt-4o-mini`).
- ERPNext instance: **v15.65** (Frappe 15.70), company **Sindh Bakery**, currency **PKR**, timezone **Asia/Karachi**.
- Data present: POS Invoices (~950), Sales Invoices (~130, all consolidated POS), Purchase Invoices (~280),
  Items (366), Bins (stock), Work Orders, BOMs, Payment Entries, Journal Entries, Departments (42),
  Cost Centers (2 leaf), Warehouses (8 leaf), 1 POS Profile. **No `Branch` records** – branch-wise
  reporting maps to Cost Center / POS Profile / Warehouse.
- POS invoices are consolidated into Sales Invoices at day close, so sales must be computed as
  `POS Invoice (submitted) + Sales Invoice (submitted, is_consolidated = 0)` to avoid double counting.
- `/api/resource` cannot join child tables with parent filters on this server, but
  `frappe.desk.reportview.get` can (`` `tabSales Invoice Item`.item_code `` syntax). The service layer uses it.
- Standard query reports (`frappe.desk.query_report.run`) work for P&L, Balance Sheet, AR/AP summaries.

## Architecture

```
frontend (Next.js 15, TS, Tailwind, shadcn/ui, lucide)
   └─ /api/* rewrite ─► backend (FastAPI)
                          ├─ api/routes        chat (SSE), conversations, uploads, export, health
                          ├─ agent/            OpenAI tool-calling loop, ERPNext-only guard, prompts
                          ├─ services/erpnext/ client (httpx) + modules/* (sales, accounts, stock, purchase,
                          │                    parties, pos, manufacturing, organization, generic)
                          ├─ files/            parsers (xlsx/xls/csv/pdf/docx/txt) + pandas analysis tool
                          ├─ export/           openpyxl Excel generator
                          └─ storage/          SQLite (conversations, messages, uploads, datasets)
```

Each ERPNext module is a Python file exposing `TOOLS: list[Tool]`. The registry collects them and
generates the OpenAI tool schema automatically, so adding a module = adding a file.

## Steps

1. Backend core: config (.env), ERPNext client, error handling, health endpoint.
2. ERPNext modules + tool registry.
3. AI agent: guard (ERPNext-only), tool loop, streaming, 10-line answers, no invented data.
4. Storage + conversations API.
5. File upload + parsing + file analysis tool.
6. Excel export.
7. Frontend UI (sidebar, history, search, chat, attachments, copy, export, loading/error, mobile).
8. Testing each feature against the live instance.
