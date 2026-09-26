"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

export function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("prose-chat", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">{children}</thead>,
          th: ({ children }) => <th className="px-3 py-2 font-semibold whitespace-nowrap">{children}</th>,
          td: ({ children }) => <td className="border-t border-border px-3 py-1.5 align-top whitespace-nowrap tabular-nums">{children}</td>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">
              {children}
            </a>
          ),
          code: ({ children, className: cls }) =>
            cls ? (
              <code className="block overflow-x-auto rounded-md bg-muted p-3 text-xs">{children}</code>
            ) : (
              <code className="rounded bg-muted px-1 py-0.5 text-[0.85em]">{children}</code>
            ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
