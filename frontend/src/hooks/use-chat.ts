"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, streamChat } from "@/lib/api";
import type { Attachment, Conversation, Message } from "@/lib/types";

const PENDING_ID = "__pending__";

export function useChat() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRef = useRef<string | null>(null);
  activeRef.current = activeId;

  const refreshConversations = useCallback(async (query?: string) => {
    try {
      const list = await api.listConversations(query);
      setConversations(list);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setConversationsLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => refreshConversations(search.trim() || undefined), search ? 250 : 0);
    return () => clearTimeout(t);
  }, [search, refreshConversations]);

  const selectConversation = useCallback(async (id: string | null) => {
    abortRef.current?.abort();
    setStreaming(false);
    setError(null);
    setActiveId(id);
    if (!id) {
      setMessages([]);
      return;
    }
    setMessagesLoading(true);
    try {
      const conv = await api.getConversation(id);
      if (activeRef.current === id) setMessages(conv.messages);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setMessagesLoading(false);
    }
  }, []);

  const newChat = useCallback(() => selectConversation(null), [selectConversation]);

  const deleteConversation = useCallback(
    async (id: string) => {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeRef.current === id) await selectConversation(null);
    },
    [selectConversation],
  );

  const renameConversation = useCallback(async (id: string, title: string) => {
    const conv = await api.renameConversation(id, title);
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title: conv.title } : c)));
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(
    async (text: string, attachments: Attachment[]) => {
      const message = text.trim();
      if (!message || streaming) return;
      setError(null);
      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(true);

      const now = new Date().toISOString();
      const conversationId = activeRef.current;
      const optimisticUser: Message = {
        id: `user-${Date.now()}`,
        conversation_id: conversationId || "",
        role: "user",
        content: message,
        attachments,
        tool_calls: [],
        datasets: [],
        created_at: now,
      };
      const pending: Message = {
        id: PENDING_ID,
        conversation_id: conversationId || "",
        role: "assistant",
        content: "",
        attachments: [],
        tool_calls: [],
        datasets: [],
        created_at: now,
        pending: true,
        status: "Connecting",
      };
      setMessages((prev) => [...prev, optimisticUser, pending]);

      const patchPending = (patch: Partial<Message> | ((m: Message) => Partial<Message>)) =>
        setMessages((prev) => prev.map((m) => (m.id === PENDING_ID ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m)));

      let finished = false;
      try {
        await streamChat(
          { message, conversation_id: conversationId, attachment_ids: attachments.map((a) => a.id) },
          (ev) => {
            switch (ev.type) {
              case "meta":
                if (!activeRef.current) {
                  activeRef.current = ev.data.conversation_id;
                  setActiveId(ev.data.conversation_id);
                }
                setMessages((prev) => prev.map((m) => (m.id === optimisticUser.id ? { ...m, id: ev.data.user_message_id, conversation_id: ev.data.conversation_id } : m)));
                break;
              case "status":
                patchPending({ status: ev.data.text });
                break;
              case "token":
                patchPending((m) => ({ content: m.content + ev.data.text, status: undefined }));
                break;
              case "reset":
                patchPending({ content: "", status: "Fetching data" });
                break;
              case "tool":
                patchPending((m) => ({ tool_calls: [...m.tool_calls, ev.data] }));
                break;
              case "done":
                finished = true;
                setMessages((prev) => prev.map((m) => (m.id === PENDING_ID ? { ...ev.data.message, pending: false } : m)));
                break;
              case "error":
                finished = true;
                patchPending({ pending: false, status: undefined, error: ev.data.message, content: "" });
                setError(ev.data.message);
                break;
            }
          },
          controller.signal,
        );
        if (!finished) patchPending({ pending: false, status: undefined, error: "The response ended unexpectedly." });
      } catch (e) {
        const aborted = (e as Error).name === "AbortError";
        patchPending((m) => ({ pending: false, status: undefined, error: aborted ? (m.content ? null : "Stopped.") : (e as Error).message }));
        if (!aborted) setError((e as Error).message);
      } finally {
        setStreaming(false);
        abortRef.current = null;
        refreshConversations(search.trim() || undefined);
      }
    },
    [streaming, refreshConversations, search],
  );

  const retryLast = useCallback(async () => {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    setMessages((prev) => prev.filter((m) => !(m.role === "assistant" && (m.error || m.pending))));
    await send(lastUser.content, lastUser.attachments);
  }, [messages, send]);

  return {
    conversations,
    conversationsLoading,
    search,
    setSearch,
    activeId,
    messages,
    messagesLoading,
    streaming,
    error,
    setError,
    send,
    stop,
    retryLast,
    newChat,
    selectConversation,
    deleteConversation,
    renameConversation,
  };
}

export type ChatController = ReturnType<typeof useChat>;
