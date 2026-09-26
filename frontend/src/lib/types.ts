export interface Attachment {
  id: string;
  filename: string;
  kind: string;
  size: number;
  preview?: string | null;
}

export interface Dataset {
  id: string;
  title: string;
  columns: string[];
  row_count: number;
}

export interface ToolCallLog {
  name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  rows: number;
  error?: string | null;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  attachments: Attachment[];
  tool_calls: ToolCallLog[];
  datasets: Dataset[];
  error?: string | null;
  created_at: string;
  /** client-only flags */
  pending?: boolean;
  status?: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface Health {
  status: string;
  erpnext: { connected: boolean; company?: string; currency?: string; error?: string; versions?: Record<string, string> };
  model: string;
  tools: number;
}

export type ChatEvent =
  | { type: "meta"; data: { conversation_id: string; title: string; user_message_id: string } }
  | { type: "status"; data: { text: string } }
  | { type: "token"; data: { text: string } }
  | { type: "reset"; data: Record<string, never> }
  | { type: "tool"; data: ToolCallLog }
  | { type: "done"; data: { message: Message; conversation_id: string; title: string } }
  | { type: "error"; data: { message: string; message_id?: string } };
