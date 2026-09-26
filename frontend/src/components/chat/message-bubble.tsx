"use client";

import { AlertCircle, Bot, Check, Copy, FileSpreadsheet, FileText, Loader2, RotateCcw, User } from "lucide-react";
import { useState } from "react";

import { Markdown } from "@/components/chat/markdown";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, downloadFile } from "@/lib/api";
import type { Attachment, Message } from "@/lib/types";
import { cn } from "@/lib/utils";

function AttachmentChip({ a }: { a: Attachment }) {
  const Icon = a.kind === "excel" || a.kind === "csv" ? FileSpreadsheet : FileText;
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-border bg-background/70 px-2 py-1 text-xs">
      <Icon className="size-3.5 shrink-0 text-muted-foreground" />
      <span className="truncate">{a.filename}</span>
      {a.preview && <span className="hidden text-muted-foreground sm:inline">· {a.preview}</span>}
    </span>
  );
}

export function MessageBubble({ message, onRetry }: { message: Message; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  const exportable = message.datasets?.length > 0 && !message.pending;

  return (
    <div className={cn("flex w-full gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser && (
        <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Bot className="size-4" />
        </div>
      )}
      <div className={cn("group flex min-w-0 max-w-[85%] flex-col gap-1.5", isUser && "items-end")}>
        {message.attachments?.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {message.attachments.map((a) => (
              <AttachmentChip key={a.id} a={a} />
            ))}
          </div>
        )}

        <div
          className={cn(
            "rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
            isUser ? "bg-primary text-primary-foreground rounded-br-md whitespace-pre-wrap" : "bg-muted/60 rounded-bl-md",
            message.error && "border border-destructive/40 bg-destructive/5",
          )}
        >
          {message.error ? (
            <div className="flex items-start gap-2 text-destructive">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <div>
                <div className="font-medium">Something went wrong</div>
                <div className="text-xs opacity-90">{message.error}</div>
              </div>
            </div>
          ) : isUser ? (
            message.content
          ) : message.pending && !message.content ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              <span className="text-xs">{message.status || "Thinking"}…</span>
            </div>
          ) : (
            <Markdown content={message.content} />
          )}
        </div>

        {!isUser && message.tool_calls?.length > 0 && (
          <div className="flex flex-wrap gap-1 px-1 text-[11px] text-muted-foreground">
            {message.tool_calls.map((t, i) => (
              <span key={i} className={cn("rounded-full border px-2 py-0.5", t.ok ? "border-border" : "border-destructive/40 text-destructive")} title={t.error || JSON.stringify(t.arguments)}>
                {t.name.replace(/_/g, " ")}
                {t.ok && t.rows ? ` · ${t.rows} rows` : ""}
              </span>
            ))}
          </div>
        )}

        {!isUser && !message.pending && (
          <div className="flex items-center gap-1 px-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 sm:opacity-0 max-sm:opacity-100">
            {message.content && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button size="icon-xs" variant="ghost" onClick={copy} aria-label="Copy response">
                    {copied ? <Check className="text-emerald-500" /> : <Copy />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{copied ? "Copied" : "Copy response"}</TooltipContent>
              </Tooltip>
            )}
            {exportable && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button size="xs" variant="outline" onClick={() => downloadFile(api.exportMessageUrl(message.id))}>
                    <FileSpreadsheet data-icon="inline-start" className="text-emerald-600" /> Export to Excel
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {message.datasets.length === 1 ? `${message.datasets[0].row_count} rows` : `${message.datasets.length} sheets`} · .xlsx with totals & filters
                </TooltipContent>
              </Tooltip>
            )}
            {message.error && onRetry && (
              <Button size="xs" variant="ghost" onClick={onRetry}>
                <RotateCcw data-icon="inline-start" /> Retry
              </Button>
            )}
          </div>
        )}
      </div>
      {isUser && (
        <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <User className="size-4" />
        </div>
      )}
    </div>
  );
}
