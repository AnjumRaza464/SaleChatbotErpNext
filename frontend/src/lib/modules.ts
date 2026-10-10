import { BarChart3, Boxes, Landmark, Shield, Truck, Users, type LucideIcon } from "lucide-react";

export type ModuleKey = "sales" | "warehouse" | "stock" | "hr" | "accounts" | "all";

export interface ModuleConfig {
  key: ModuleKey;
  label: string;
  description: string;
  icon: LucideIcon;
  /** Tailwind classes for the active tab / avatar accent. */
  accent: string;
  placeholder: string;
  suggestions: string[];
}

export const MODULES: Record<ModuleKey, ModuleConfig> = {
  sales: {
    key: "sales",
    label: "Sales",
    description: "Sales reports, revenue, POS, customers, receivables and branch comparisons",
    icon: BarChart3,
    accent: "bg-blue-600 text-white",
    placeholder: "Ask about sales, revenue, invoices, customers, POS…",
    suggestions: [
      "What were today's sales?",
      "Compare this month's sales with last month",
      "Item-wise sales this month, top 10",
      "Branch-wise sales this week",
      "Show outstanding customer invoices",
      "Top 5 customers by sales this month",
    ],
  },
  warehouse: {
    key: "warehouse",
    label: "Warehouse",
    description: "Warehouse operations: receipts, dispatches, transfers, stock movement",
    icon: Truck,
    accent: "bg-amber-600 text-white",
    placeholder: "Ask about stock entries, receipts, transfers, material requests…",
    suggestions: [
      "Stock entries today",
      "Material transfers this week by warehouse",
      "Pending material requests",
      "Purchase receipts this month",
      "Stock movement summary for last 7 days",
      "Delivery notes pending for today",
    ],
  },
  stock: {
    key: "stock",
    label: "Stock",
    description: "Stock balances, low-stock items, item master and availability",
    icon: Boxes,
    accent: "bg-emerald-600 text-white",
    placeholder: "Ask about stock balance, low stock, items, warehouses…",
    suggestions: [
      "Which items are low on stock?",
      "Stock balance by warehouse",
      "Current stock of Mix Sweets",
      "Items with zero stock",
      "Total stock value by item group",
      "List items in group Cakes",
    ],
  },
  hr: {
    key: "hr",
    label: "HR",
    description: "Employees, attendance, leave, departments and HR reports",
    icon: Users,
    accent: "bg-violet-600 text-white",
    placeholder: "Ask about employees, attendance, leave, departments…",
    suggestions: [
      "How many active employees do we have?",
      "Attendance summary for this week",
      "Who is on leave today?",
      "Pending leave applications",
      "Employees by department",
      "Upcoming holidays this month",
    ],
  },
  accounts: {
    key: "accounts",
    label: "Accounts",
    description: "Receivables, payables, payments, ledgers, P&L, balance sheet and journal entries",
    icon: Landmark,
    accent: "bg-rose-600 text-white",
    placeholder: "Ask about receivables, payables, payments, ledger, P&L…",
    suggestions: [
      "Which customers owe us money?",
      "Which suppliers do we owe money to?",
      "Profit and loss for this month",
      "Payments received this week",
      "Overdue invoices older than 30 days",
      "Journal entries posted this month",
    ],
  },
  all: {
    key: "all",
    label: "All",
    description: "Administrator view: every ERPNext area",
    icon: Shield,
    accent: "bg-primary text-primary-foreground",
    placeholder: "Ask about anything in ERPNext…",
    suggestions: [
      "What were today's sales?",
      "Which items are low on stock?",
      "Which suppliers do we owe money to?",
      "Profit and loss this month",
      "Stock entries today",
      "How many active employees do we have?",
    ],
  },
};

export const MODULE_ORDER: ModuleKey[] = ["sales", "warehouse", "stock", "hr", "accounts", "all"];

export function moduleConfig(key: string | null | undefined): ModuleConfig {
  return (key && MODULES[key as ModuleKey]) || MODULES.all;
}
