"use client";

import { Check, MessageSquare, MoreHorizontal, Moon, Pencil, Plus, Search, Sun, Trash2, X } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore, useState } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { Conversation, Health } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SidebarProps {
  conversations: Conversation[];
  loading: boolean;
  activeId: string | null;
  search: string;
  onSearch: (v: string) => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => Promise<void>;
  onRename: (id: string, title: string) => Promise<void>;
  health: Health | null;
}

function groupLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.floor((startOfToday.getTime() - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86400000);
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return "Previous 7 days";
  if (diffDays < 30) return "Previous 30 days";
  return "Older";
}

export function Sidebar({ conversations, loading, activeId, search, onSearch, onNewChat, onSelect, onDelete, onRename, health }: SidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false);

  const groups: Record<string, Conversation[]> = {};
  for (const c of conversations) (groups[groupLabel(c.updated_at)] ||= []).push(c);
  const order = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"];

  const commitRename = async (id: string) => {
    const title = draft.trim();
    setEditingId(null);
    if (title) await onRename(id, title);
  };

  return (
    <aside className="flex h-full w-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex items-center gap-2 px-3 pt-3 pb-2">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground text-sm font-bold">E</div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">ERPNext Assistant</div>
          <div className="truncate text-[11px] text-muted-foreground">
            {health ? (health.erpnext.connected ? `${health.erpnext.company ?? "Connected"} · ${health.erpnext.currency ?? ""}` : "ERPNext offline") : "Connecting…"}
          </div>
        </div>
        <span
          className={cn("size-2 shrink-0 rounded-full", health?.erpnext.connected ? "bg-emerald-500" : health ? "bg-red-500" : "bg-amber-400 animate-pulse")}
          title={health?.erpnext.connected ? "ERPNext connected" : health?.erpnext.error || "Checking connection"}
        />
      </div>

      <div className="px-3 pb-2">
        <Button className="w-full justify-start" variant="outline" onClick={onNewChat}>
          <Plus data-icon="inline-start" /> New chat
        </Button>
      </div>

      <div className="relative px-3 pb-2">
        <Search className="pointer-events-none absolute top-1/2 left-5.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Search conversations" className="h-8 bg-background pl-8 text-sm" />
        {search && (
          <button onClick={() => onSearch("")} className="absolute top-1/2 right-5 -translate-y-1/2 text-muted-foreground hover:text-foreground" aria-label="Clear search">
            <X className="size-3.5" />
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {loading ? (
          <div className="space-y-2 px-1 pt-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : conversations.length === 0 ? (
          <p className="px-2 pt-6 text-center text-xs text-muted-foreground">{search ? "No conversations match your search." : "No conversations yet. Ask your first ERPNext question."}</p>
        ) : (
          order
            .filter((g) => groups[g]?.length)
            .map((g) => (
              <div key={g} className="mb-2">
                <div className="px-2 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{g}</div>
                {groups[g].map((c) => (
                  <div
                    key={c.id}
                    className={cn(
                      "group flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm transition-colors",
                      c.id === activeId ? "bg-sidebar-accent text-sidebar-accent-foreground" : "hover:bg-sidebar-accent/60",
                    )}
                  >
                    {editingId === c.id ? (
                      <form
                        className="flex min-w-0 flex-1 items-center gap-1"
                        onSubmit={(e) => {
                          e.preventDefault();
                          commitRename(c.id);
                        }}
                      >
                        <Input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} className="h-7 text-sm" onBlur={() => commitRename(c.id)} />
                        <Button type="submit" size="icon-xs" variant="ghost" aria-label="Save">
                          <Check />
                        </Button>
                      </form>
                    ) : (
                      <>
                        <button onClick={() => onSelect(c.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left" title={c.title}>
                          <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
                          <span className="truncate">{c.title}</span>
                        </button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button size="icon-xs" variant="ghost" className="opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100" aria-label="Conversation options">
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onClick={() => {
                                setEditingId(c.id);
                                setDraft(c.title);
                              }}
                            >
                              <Pencil /> Rename
                            </DropdownMenuItem>
                            <DropdownMenuItem variant="destructive" onClick={() => onDelete(c.id)}>
                              <Trash2 /> Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </>
                    )}
                  </div>
                ))}
              </div>
            ))
        )}
      </div>

      <div className="flex items-center justify-between border-t border-sidebar-border px-3 py-2 text-[11px] text-muted-foreground">
        <span className="truncate">{health ? `${health.tools} tools · ${health.model}` : ""}</span>
        <Button size="icon-xs" variant="ghost" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")} aria-label="Toggle theme">
          {mounted && resolvedTheme === "dark" ? <Sun /> : <Moon />}
        </Button>
      </div>
    </aside>
  );
}
