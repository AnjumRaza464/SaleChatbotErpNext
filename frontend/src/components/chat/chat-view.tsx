"use client";

import { AlertCircle, BarChart3, Boxes, Menu, Receipt, Sparkles, Users, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { Composer } from "@/components/chat/composer";
import { MessageBubble } from "@/components/chat/message-bubble";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChatController } from "@/hooks/use-chat";
import type { Attachment, Health } from "@/lib/types";

const SUGGESTIONS = [
  { icon: BarChart3, text: "What were today's sales?" },
  { icon: BarChart3, text: "Compare this month's sales with last month" },
  { icon: Receipt, text: "Show outstanding customer invoices" },
  { icon: Boxes, text: "Which items are low on stock?" },
  { icon: Users, text: "Top 5 suppliers by purchases this month" },
  { icon: Sparkles, text: "Item-wise sales for this week" },
];

interface ChatViewProps {
  chat: ChatController;
  health: Health | null;
  onOpenSidebar: () => void;
  title?: string;
}

export function ChatView({ chat, health, onOpenSidebar, title }: ChatViewProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const { messages, messagesLoading, streaming, send, stop, error, setError, retryLast } = chat;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streaming ? "auto" : "smooth", block: "end" });
  }, [messages, streaming]);

  const handleSend = (text: string, attachments: Attachment[]) => send(text, attachments);
  const empty = messages.length === 0 && !messagesLoading;

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col bg-background">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <Button size="icon-sm" variant="ghost" className="md:hidden" onClick={onOpenSidebar} aria-label="Open menu">
          <Menu />
        </Button>
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium">{title || "New chat"}</h1>
        {health && !health.erpnext.connected && (
          <span className="flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] text-destructive">
            <AlertCircle className="size-3" /> ERPNext offline
          </span>
        )}
      </header>

      {error && (
        <div className="flex items-center gap-2 border-b border-destructive/30 bg-destructive/5 px-4 py-2 text-xs text-destructive">
          <AlertCircle className="size-3.5 shrink-0" />
          <span className="min-w-0 flex-1 truncate">{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss error" className="rounded p-0.5 hover:bg-destructive/10">
            <X className="size-3.5" />
          </button>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6">
          {messagesLoading ? (
            <div className="space-y-4">
              <Skeleton className="ml-auto h-10 w-2/3" />
              <Skeleton className="h-24 w-4/5" />
              <Skeleton className="ml-auto h-10 w-1/2" />
              <Skeleton className="h-20 w-3/4" />
            </div>
          ) : empty ? (
            <div className="flex flex-col items-center gap-6 pt-10 text-center sm:pt-20">
              <div className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
                <Sparkles className="size-6" />
              </div>
              <div>
                <h2 className="text-xl font-semibold">ERPNext AI Assistant</h2>
                <p className="mt-1 max-w-md text-sm text-muted-foreground">
                  Ask questions about live ERPNext data across Sales, Accounts, Stock, Purchase, POS, Manufacturing and more. Attach Excel, CSV, PDF or Word files for analysis.
                </p>
              </div>
              <div className="grid w-full max-w-2xl grid-cols-1 gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s.text}
                    onClick={() => handleSend(s.text, [])}
                    className="flex items-center gap-2.5 rounded-xl border border-border bg-card px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted"
                  >
                    <s.icon className="size-4 shrink-0 text-muted-foreground" />
                    <span>{s.text}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) => <MessageBubble key={m.id} message={m} onRetry={retryLast} />)
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-background px-3 pt-3 pb-3 sm:px-4">
        <div className="mx-auto w-full max-w-3xl">
          <Composer streaming={streaming} onSend={handleSend} onStop={stop} autoFocus />
          <p className="mt-2 text-center text-[11px] text-muted-foreground">Answers come from live ERPNext data. Only ERPNext-related questions are answered.</p>
        </div>
      </div>
    </div>
  );
}
