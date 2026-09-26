import type { Attachment, ChatEvent, Conversation, ConversationDetail, Health } from "@/lib/types";

const BASE = "/api";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => fetch(`${BASE}/health`, { cache: "no-store" }).then((r) => handle<Health>(r)),

  listConversations: (search?: string) =>
    fetch(`${BASE}/conversations${search ? `?search=${encodeURIComponent(search)}` : ""}`, { cache: "no-store" }).then((r) =>
      handle<Conversation[]>(r),
    ),

  getConversation: (id: string) => fetch(`${BASE}/conversations/${id}`, { cache: "no-store" }).then((r) => handle<ConversationDetail>(r)),

  createConversation: (title = "New chat") =>
    fetch(`${BASE}/conversations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }).then((r) =>
      handle<Conversation>(r),
    ),

  renameConversation: (id: string, title: string) =>
    fetch(`${BASE}/conversations/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }).then((r) =>
      handle<ConversationDetail>(r),
    ),

  deleteConversation: (id: string) => fetch(`${BASE}/conversations/${id}`, { method: "DELETE" }).then((r) => handle<void>(r)),

  upload: async (file: File): Promise<Attachment> => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/uploads`, { method: "POST", body: form }).then((r) => handle<Attachment>(r));
  },

  exportMessageUrl: (messageId: string) => `${BASE}/export/message/${messageId}`,
  exportDatasetUrl: (datasetId: string) => `${BASE}/export/dataset/${datasetId}`,
};

/**
 * Stream a chat response. Calls `onEvent` for each SSE event.
 */
export async function streamChat(
  body: { message: string; conversation_id?: string | null; attachment_ids: string[] },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || "Chat request failed");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let type = "message";
      let data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) type = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      try {
        onEvent({ type, data: JSON.parse(data) } as ChatEvent);
      } catch {
        /* malformed chunk, ignore */
      }
    }
  }
}

export function downloadFile(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
