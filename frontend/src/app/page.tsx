"use client";

import { Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { ChatView } from "@/components/chat/chat-view";
import { ModuleTabs } from "@/components/chat/module-tabs";
import { Sidebar } from "@/components/chat/sidebar";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useChat } from "@/hooks/use-chat";
import { SESSION_EXPIRED_EVENT, api } from "@/lib/api";
import { MODULE_ORDER, type ModuleKey } from "@/lib/modules";
import type { Health, User } from "@/lib/types";

function Home() {
  const router = useRouter();
  const params = useSearchParams();
  const [user, setUser] = useState<User | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Session check: unauthenticated visitors go to /login, and any later 401
  // (expired cookie, disabled account) sends them back there too.
  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => router.replace("/login"));
    const expired = () => router.replace("/login");
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  }, [router]);

  // Tabs the user may open, in display order; the active one lives in the URL.
  const tabs = useMemo(() => MODULE_ORDER.filter((m) => user?.modules.includes(m)), [user]);
  const requested = params.get("tab");
  const activeModule: ModuleKey | null = tabs.length ? (tabs.includes(requested as ModuleKey) ? (requested as ModuleKey) : tabs[0]) : null;

  useEffect(() => {
    if (activeModule && requested !== activeModule) router.replace(`/?tab=${activeModule}`);
  }, [activeModule, requested, router]);

  const setTab = useCallback(
    (m: ModuleKey) => {
      router.replace(`/?tab=${m}`);
      setMobileOpen(false);
    },
    [router],
  );

  const chat = useChat(activeModule);

  useEffect(() => {
    if (!user) return;
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
  }, [user]);

  const logout = async () => {
    await api.logout().catch(() => {});
    router.replace("/login");
  };

  if (!user) {
    return (
      <div className="flex h-dvh items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

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
      user={user}
      module={activeModule}
      onLogout={logout}
    />
  );

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-dvh w-full flex-col overflow-hidden">
        <ModuleTabs tabs={tabs} active={activeModule} onSelect={setTab} />
        <div className="flex min-h-0 flex-1">
          <div className="hidden w-72 shrink-0 border-r border-sidebar-border md:block">{sidebar}</div>
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetContent side="left" className="w-80 p-0 sm:max-w-80" showCloseButton={false}>
              <SheetTitle className="sr-only">Conversations</SheetTitle>
              {sidebar}
            </SheetContent>
          </Sheet>
          {activeModule ? (
            <ChatView chat={chat} health={health} onOpenSidebar={() => setMobileOpen(true)} title={activeTitle} module={activeModule} />
          ) : (
            <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-muted-foreground">
              No modules have been assigned to your account yet. Ask an administrator for access.
            </div>
          )}
        </div>
      </div>
    </TooltipProvider>
  );
}

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="flex h-dvh items-center justify-center">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <Home />
    </Suspense>
  );
}
