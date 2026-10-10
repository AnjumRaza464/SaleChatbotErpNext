import type { Attachment, ChatEvent, Conversation, ConversationDetail, Health, User } from "@/lib/types";

const BASE = "/api";

/** Fired on any 401 so the page can send the user back to /login. */
export const SESSION_EXPIRED_EVENT = "erp:session-expired";

function notifySessionExpired() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    if (res.status === 401) notifySessionExpired();
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (method: string, body: unknown) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: () => fetch(`${BASE}/health`, { cache: "no-store" }).then((r) => handle<Health>(r)),

  // ---- auth
  login: (email: string, password: string) => fetch(`${BASE}/auth/login`, json("POST", { email, password })).then((r) => handle<User>(r)),
  logout: () => fetch(`${BASE}/auth/logout`, { method: "POST" }).then((r) => handle<void>(r)),
  me: () => fetch(`${BASE}/auth/me`, { cache: "no-store" }).then((r) => handle<User>(r)),

  // ---- conversations (always scoped to a module)
  listConversations: (module: string, search?: string) => {
    const q = new URLSearchParams({ module });
    if (search) q.set("search", search);
    return fetch(`${BASE}/conversations?${q}`, { cache: "no-store" }).then((r) => handle<Conversation[]>(r));
  },

  getConversation: (id: string) => fetch(`${BASE}/conversations/${id}`, { cache: "no-store" }).then((r) => handle<ConversationDetail>(r)),

  createConversation: (module: string, title = "New chat") => fetch(`${BASE}/conversations`, json("POST", { title, module })).then((r) => handle<Conversation>(r)),

  renameConversation: (id: string, title: string) => fetch(`${BASE}/conversations/${id}`, json("PATCH", { title })).then((r) => handle<ConversationDetail>(r)),

  deleteConversation: (id: string) => fetch(`${BASE}/conversations/${id}`, { method: "DELETE" }).then((r) => handle<void>(r)),

  upload: async (file: File): Promise<Attachment> => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/uploads`, { method: "POST", body: form }).then((r) => handle<Attachment>(r));
  },

  transcribe: async (audio: Blob, filename: string): Promise<{ text: string }> => {
    const form = new FormData();
    form.append("file", audio, filename);
    return fetch(`${BASE}/transcribe`, { method: "POST", body: form }).then((r) => handle<{ text: string }>(r));
  },

  exportMessageUrl: (messageId: string) => `${BASE}/export/message/${messageId}`,
  exportDatasetUrl: (datasetId: string) => `${BASE}/export/dataset/${datasetId}`,

  // ---- admin
  admin: {
    listUsers: () => fetch(`${BASE}/admin/users`, { cache: "no-store" }).then((r) => handle<User[]>(r)),
    createUser: (body: { email: string; full_name: string; password: string; modules: string[]; is_admin: boolean }) =>
      fetch(`${BASE}/admin/users`, json("POST", body)).then((r) => handle<User>(r)),
    updateUser: (id: string, body: Partial<{ full_name: string; password: string; modules: string[]; is_admin: boolean; is_active: boolean }>) =>
      fetch(`${BASE}/admin/users/${id}`, json("PATCH", body)).then((r) => handle<User>(r)),
    deleteUser: (id: string) => fetch(`${BASE}/admin/users/${id}`, { method: "DELETE" }).then((r) => handle<void>(r)),
  },
};

/**
 * Stream a chat response. Calls `onEvent` for each SSE event.
 */
export async function streamChat(
  body: { message: string; conversation_id?: string | null; attachment_ids: string[]; module: string },
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
    if (res.status === 401) notifySessionExpired();
    throw new ApiError(detail || "Chat request failed", res.status);
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
