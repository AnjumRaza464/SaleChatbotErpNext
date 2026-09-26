"use client";

import { ArrowUp, FileSpreadsheet, FileText, Loader2, Paperclip, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import type { Attachment } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPT = ".xlsx,.xls,.xlsm,.csv,.tsv,.pdf,.docx,.txt,.md";

interface PendingUpload {
  localId: string;
  name: string;
  uploading: boolean;
  error?: string;
  attachment?: Attachment;
}

interface ComposerProps {
  disabled?: boolean;
  streaming: boolean;
  onSend: (text: string, attachments: Attachment[]) => void;
  onStop: () => void;
  autoFocus?: boolean;
}

export function Composer({ disabled, streaming, onSend, onStop, autoFocus }: ComposerProps) {
  const [text, setText] = useState("");
  const [uploads, setUploads] = useState<PendingUpload[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const addFiles = (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      const localId = `${file.name}-${Date.now()}-${Math.random()}`;
      setUploads((prev) => [...prev, { localId, name: file.name, uploading: true }]);
      api
        .upload(file)
        .then((att) => setUploads((prev) => prev.map((u) => (u.localId === localId ? { ...u, uploading: false, attachment: att } : u))))
        .catch((e: Error) => setUploads((prev) => prev.map((u) => (u.localId === localId ? { ...u, uploading: false, error: e.message } : u))));
    }
  };

  const ready = uploads.filter((u) => u.attachment).map((u) => u.attachment!);
  const uploading = uploads.some((u) => u.uploading);
  const canSend = text.trim().length > 0 && !uploading && !streaming && !disabled;

  const submit = () => {
    if (!canSend) return;
    onSend(text, ready);
    setText("");
    setUploads([]);
    textarea.current?.focus();
  };

  return (
    <div
      className={cn("relative rounded-2xl border border-border bg-background shadow-sm transition-colors focus-within:border-ring", dragging && "border-primary bg-primary/5")}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
      }}
    >
      {uploads.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 pt-3">
          {uploads.map((u) => {
            const Icon = /\.(xlsx|xls|xlsm|csv|tsv)$/i.test(u.name) ? FileSpreadsheet : FileText;
            return (
              <span
                key={u.localId}
                className={cn("inline-flex max-w-[260px] items-center gap-1.5 rounded-lg border px-2 py-1 text-xs", u.error ? "border-destructive/50 text-destructive" : "border-border bg-muted/50")}
                title={u.error || u.attachment?.preview || u.name}
              >
                {u.uploading ? <Loader2 className="size-3.5 animate-spin" /> : <Icon className="size-3.5 text-muted-foreground" />}
                <span className="truncate">{u.name}</span>
                {u.attachment?.preview && <span className="hidden text-muted-foreground sm:inline">· {u.attachment.preview}</span>}
                <button type="button" onClick={() => setUploads((prev) => prev.filter((x) => x.localId !== u.localId))} className="ml-0.5 rounded hover:bg-muted" aria-label="Remove attachment">
                  <X className="size-3" />
                </button>
              </span>
            );
          })}
        </div>
      )}
      <Textarea
        ref={textarea}
        value={text}
        autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="Ask about sales, stock, invoices, customers… or attach a file to analyze"
        rows={1}
        disabled={disabled}
        className="max-h-[200px] min-h-[44px] resize-none border-0 bg-transparent px-4 py-3 text-[15px] shadow-none focus-visible:ring-0 dark:bg-transparent"
      />
      <div className="flex items-center justify-between px-2 pb-2">
        <div className="flex items-center gap-1">
          <input ref={fileInput} type="file" accept={ACCEPT} multiple hidden onChange={(e) => e.target.files && addFiles(e.target.files)} />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button type="button" size="icon-sm" variant="ghost" onClick={() => fileInput.current?.click()} disabled={disabled} aria-label="Attach file">
                <Paperclip />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Attach Excel, CSV, PDF, DOCX or TXT</TooltipContent>
          </Tooltip>
          <span className="hidden text-[11px] text-muted-foreground sm:inline">Enter to send · Shift+Enter for new line</span>
        </div>
        {streaming ? (
          <Button type="button" size="icon-sm" variant="outline" onClick={onStop} aria-label="Stop generating">
            <Square className="size-3 fill-current" />
          </Button>
        ) : (
          <Button type="button" size="icon-sm" onClick={submit} disabled={!canSend} aria-label="Send message">
            <ArrowUp />
          </Button>
        )}
      </div>
    </div>
  );
}
