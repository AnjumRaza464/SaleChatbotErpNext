"use client";

import { MODULES, type ModuleKey } from "@/lib/modules";
import { cn } from "@/lib/utils";

interface ModuleTabsProps {
  tabs: ModuleKey[];
  active: ModuleKey | null;
  onSelect: (m: ModuleKey) => void;
}

/** Top-level module switcher. Only the modules the user holds are rendered. */
export function ModuleTabs({ tabs, active, onSelect }: ModuleTabsProps) {
  if (tabs.length === 0) return null;
  return (
    <nav aria-label="Modules" className="flex h-11 shrink-0 items-stretch gap-1 overflow-x-auto border-b border-border bg-sidebar px-2">
      {tabs.map((key) => {
        const m = MODULES[key];
        const on = key === active;
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onSelect(key)}
            title={m.description}
            className={cn(
              "relative flex items-center gap-2 whitespace-nowrap rounded-t-lg px-3 text-sm transition-colors",
              on ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <span className={cn("flex size-5 items-center justify-center rounded-md", on ? m.accent : "bg-muted text-muted-foreground")}>
              <m.icon className="size-3.5" />
            </span>
            {m.label}
            {on && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-foreground" />}
          </button>
        );
      })}
    </nav>
  );
}
