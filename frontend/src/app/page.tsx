"use client";

import { useEffect, useState } from "react";

import { ChatView } from "@/components/chat/chat-view";
import { Sidebar } from "@/components/chat/sidebar";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useChat } from "@/hooks/use-chat";
import { api } from "@/lib/api";
import type { Health } from "@/lib/types";

export default function Home() {
  const chat = useChat();
  const [health, setHealth] = useState<Health | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .health()
        .then((h) => !cancelled && setHealth(h))
        .catch((e: Error) => !cancelled && setHealth({ status: "down", erpnext: { connected: false, error: e.message }, model: "", tools: 0 }));
    load();
    const t = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const activeTitle = chat.conversations.find((c) => c.id === chat.activeId)?.title;

  const sidebar = (
    <Sidebar
      conversations={chat.conversations}
      loading={chat.conversationsLoading}
      activeId={chat.activeId}
      search={chat.search}
      onSearch={chat.setSearch}
      onNewChat={() => {
        chat.newChat();
        setMobileOpen(false);
      }}
      onSelect={(id) => {
        chat.selectConversation(id);
        setMobileOpen(false);
      }}
      onDelete={chat.deleteConversation}
      onRename={chat.renameConversation}
      health={health}
    />
  );

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-dvh w-full overflow-hidden">
        <div className="hidden w-72 shrink-0 border-r border-sidebar-border md:block">{sidebar}</div>
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="w-80 p-0 sm:max-w-80" showCloseButton={false}>
            <SheetTitle className="sr-only">Conversations</SheetTitle>
            {sidebar}
          </SheetContent>
        </Sheet>
        <ChatView chat={chat} health={health} onOpenSidebar={() => setMobileOpen(true)} title={activeTitle} />
      </div>
    </TooltipProvider>
  );
}
