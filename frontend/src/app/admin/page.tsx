"use client";

import { ArrowLeft, Check, KeyRound, Loader2, Plus, ShieldCheck, Trash2, UserX, UserCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { MODULES, type ModuleKey } from "@/lib/modules";
import type { User } from "@/lib/types";
import { cn } from "@/lib/utils";

const ASSIGNABLE: ModuleKey[] = ["sales", "warehouse", "stock", "hr", "accounts"];

export default function AdminPage() {
  const router = useRouter();
  const [me, setMe] = useState<User | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [form, setForm] = useState({ email: "", full_name: "", password: "", modules: [] as string[], is_admin: false });
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((u) => {
        if (!u.is_admin) {
          router.replace("/");
          return null;
        }
        return api.admin.listUsers().then((list) => {
          if (cancelled) return null;
          setMe(u);
          setUsers(list);
          return list;
        });
      })
      .catch(() => router.replace("/login"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [router]);

  const run = async (id: string, fn: () => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await fn();
      setUsers(await api.admin.listUsers());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const toggleModule = (u: User, m: string) => {
    const next = u.modules.includes(m) ? u.modules.filter((x) => x !== m) : [...u.modules.filter((x) => x !== "all"), m];
    return run(u.id, () => api.admin.updateUser(u.id, { modules: next.filter((x) => x !== "all") }));
  };

  const resetPassword = (u: User) => {
    const pw = window.prompt(`New password for ${u.email} (min 8 characters):`);
    if (!pw) return;
    return run(u.id, () => api.admin.updateUser(u.id, { password: pw }));
  };

  const remove = (u: User) => {
    if (!window.confirm(`Delete ${u.email} and all their conversations?`)) return;
    return run(u.id, () => api.admin.deleteUser(u.id));
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await api.admin.createUser(form);
      setForm({ email: "", full_name: "", password: "", modules: [], is_admin: false });
      setUsers(await api.admin.listUsers());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </main>
    );
  }

  return (
    <main className="mx-auto min-h-dvh w-full max-w-5xl px-4 py-6">
      <header className="mb-6 flex items-center gap-3">
        <Button asChild size="icon-sm" variant="ghost" aria-label="Back to chat">
          <Link href="/">
            <ArrowLeft />
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <ShieldCheck className="size-5" /> Users &amp; access
          </h1>
          <p className="text-xs text-muted-foreground">Assign chatbot modules to each user. Checks are enforced on the server for every request.</p>
        </div>
        <span className="text-xs text-muted-foreground">{me?.email}</span>
      </header>

      {error && (
        <p role="alert" className="mb-4 rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          {error}
        </p>
      )}

      <section className="mb-8 overflow-x-auto rounded-2xl border border-border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2">User</th>
              {ASSIGNABLE.map((m) => (
                <th key={m} className="px-3 py-2 text-center">
                  {MODULES[m].label}
                </th>
              ))}
              <th className="px-3 py-2 text-center">Admin</th>
              <th className="px-3 py-2 text-center">Status</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const busy = busyId === u.id;
              const self = u.id === me?.id;
              return (
                <tr key={u.id} className={cn("border-t border-border", !u.is_active && "opacity-60")}>
                  <td className="px-3 py-2">
                    <div className="font-medium">{u.full_name}</div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </td>
                  {ASSIGNABLE.map((m) => {
                    const on = u.is_admin || u.modules.includes(m);
                    return (
                      <td key={m} className="px-3 py-2 text-center">
                        <button
                          type="button"
                          disabled={busy || u.is_admin}
                          onClick={() => toggleModule(u, m)}
                          aria-pressed={on}
                          aria-label={`${MODULES[m].label} access for ${u.email}`}
                          className={cn(
                            "inline-flex size-7 items-center justify-center rounded-md border transition-colors",
                            on ? MODULES[m].accent + " border-transparent" : "border-border hover:bg-muted",
                            u.is_admin && "cursor-not-allowed",
                          )}
                        >
                          {on && <Check className="size-4" />}
                        </button>
                      </td>
                    );
                  })}
                  <td className="px-3 py-2 text-center">
                    <button
                      type="button"
                      disabled={busy || self}
                      onClick={() => run(u.id, () => api.admin.updateUser(u.id, { is_admin: !u.is_admin }))}
                      aria-pressed={u.is_admin}
                      className={cn("inline-flex size-7 items-center justify-center rounded-md border", u.is_admin ? "border-transparent bg-foreground text-background" : "border-border hover:bg-muted")}
                      aria-label={`Administrator for ${u.email}`}
                    >
                      {u.is_admin && <Check className="size-4" />}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <Badge variant={u.is_active ? "secondary" : "destructive"}>{u.is_active ? "Active" : "Disabled"}</Badge>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1">
                      {busy && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
                      <Button size="icon-xs" variant="ghost" onClick={() => resetPassword(u)} aria-label="Reset password" title="Reset password">
                        <KeyRound />
                      </Button>
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        disabled={self}
                        onClick={() => run(u.id, () => api.admin.updateUser(u.id, { is_active: !u.is_active }))}
                        aria-label={u.is_active ? "Disable user" : "Enable user"}
                        title={u.is_active ? "Disable" : "Enable"}
                      >
                        {u.is_active ? <UserX /> : <UserCheck />}
                      </Button>
                      <Button size="icon-xs" variant="ghost" disabled={self} onClick={() => remove(u)} aria-label="Delete user" title="Delete">
                        <Trash2 />
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="rounded-2xl border border-border p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Plus className="size-4" /> Add user
        </h2>
        <form onSubmit={create} className="grid gap-3 sm:grid-cols-2">
          <Input placeholder="Full name" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <Input type="email" placeholder="Email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Input type="password" placeholder="Password (min 8 characters)" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <div className="flex flex-wrap items-center gap-3 text-sm">
            {ASSIGNABLE.map((m) => (
              <label key={m} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={form.modules.includes(m)}
                  onChange={(e) => setForm({ ...form, modules: e.target.checked ? [...form.modules, m] : form.modules.filter((x) => x !== m) })}
                />
                {MODULES[m].label}
              </label>
            ))}
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={form.is_admin} onChange={(e) => setForm({ ...form, is_admin: e.target.checked })} /> Admin
            </label>
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={creating}>
              {creating ? <Loader2 className="animate-spin" /> : <Plus />} Create user
            </Button>
          </div>
        </form>
      </section>
    </main>
  );
}
