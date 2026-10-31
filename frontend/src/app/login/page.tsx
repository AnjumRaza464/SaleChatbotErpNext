"use client";

import { ArrowRight, BarChart3, Boxes, Eye, EyeOff, Landmark, Loader2, Lock, Mail, Mic, ShieldCheck, TrendingUp, Users } from "lucide-react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { SalesScene } from "@/components/login/sales-scene";
import { api } from "@/lib/api";

const FEATURES = [
  { icon: BarChart3, title: "Sales & POS, live", text: "Today's sales, branch and item-wise, counter and cashier totals." },
  { icon: Boxes, title: "Stock & warehouse", text: "Balances, low-stock alerts, receipts, transfers and movement." },
  { icon: Users, title: "HR & attendance", text: "Headcount, who is absent today, leave balances and holidays." },
  { icon: Landmark, title: "Accounts in one ask", text: "Receivables, payables, P&L, ledgers and payments." },
];

export default function LoginPage() {
  const router = useRouter();
  const cardRef = useRef<HTMLFormElement>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in? Go straight to the chat.
  useEffect(() => {
    api
      .me()
      .then(() => router.replace("/"))
      .catch(() => {});
  }, [router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login(email.trim(), password);
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  // 3D tilt + cursor-following glow on the card.
  const onCardMove = (e: React.PointerEvent<HTMLFormElement>) => {
    const el = cardRef.current;
    if (!el || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    el.style.setProperty("--cy", `${((px - 0.5) * 9).toFixed(2)}deg`);
    el.style.setProperty("--cx", `${((0.5 - py) * 9).toFixed(2)}deg`);
    el.style.setProperty("--gx", `${(px * 100).toFixed(1)}%`);
    el.style.setProperty("--gy", `${(py * 100).toFixed(1)}%`);
    el.classList.add("is-tilting");
  };
  const onCardLeave = () => {
    const el = cardRef.current;
    if (!el) return;
    el.classList.remove("is-tilting");
    el.style.setProperty("--cx", "0deg");
    el.style.setProperty("--cy", "0deg");
  };

  return (
    <main className="lp-root">
      <SalesScene />

      <div className="lp-layout">
        {/* ---------------------------------------------------------- hero */}
        <section className="lp-hero">
          <div className="lp-brand">
            <Image src="/sindh-bakery-logo.png" alt="The Sindh Bakery" width={491} height={176} priority className="lp-brand-logo" />
            <span className="lp-brand-divider" />
            <span>
              <strong>Sales Chatbot</strong>
              <small>ERPNext AI Assistant</small>
            </span>
          </div>

          <div className="lp-pill">
            <i />
            Sales chatbot · live ERPNext data · voice enabled
          </div>

          <h1 className="lp-title">
            Your sales numbers,
            <br />
            <span className="lp-title-accent">one question away.</span>
          </h1>
          <p className="lp-lead">
            Ask in plain English or Urdu: today&apos;s sales, branch comparisons, who owes you money, what is low in stock.
            The bot reads your live ERPNext and answers with the numbers behind it.
          </p>

          <ul className="lp-features">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="lp-feature">
                <span className="lp-feature-icon">
                  <Icon className="size-4" />
                </span>
                <div>
                  <strong>{title}</strong>
                  <p>{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* ---------------------------------------------------------- card */}
        <section className="lp-card-wrap">
          <div className="lp-bubbles" aria-hidden="true">
            <div className="lp-bubble lp-bubble-user lp-b1">
              <span className="lp-bubble-tag">You</span>
              What were today&apos;s sales?
            </div>
            <div className="lp-bubble lp-bubble-bot lp-b2">
              <span className="lp-bubble-tag">
                <BarChart3 className="size-3" /> Sales bot
              </span>
              <div className="lp-kpi">PKR 1,284,500</div>
              <div className="lp-kpi-sub">
                <TrendingUp className="size-3" /> +12.4% vs yesterday · 3 branches
              </div>
            </div>
            <div className="lp-bubble lp-bubble-bot lp-b3">
              <span className="lp-bubble-tag">Top customers this month</span>
              <div className="lp-mini-row">
                <span>Ali Traders</span>
                <b>412,900</b>
              </div>
              <div className="lp-mini-row">
                <span>City Mart</span>
                <b>298,150</b>
              </div>
              <div className="lp-mini-bar">
                <i style={{ width: "100%" }} />
                <i style={{ width: "72%" }} />
              </div>
            </div>
            <div className="lp-bubble lp-voice lp-b4">
              <span className="lp-voice-ring" />
              <span className="lp-voice-ring lp-voice-ring-2" />
              <Mic className="size-4" />
              <span>Ask by voice</span>
            </div>
          </div>

          <form ref={cardRef} onSubmit={submit} onPointerMove={onCardMove} onPointerLeave={onCardLeave} className="lp-card">
            <div className="lp-card-icon">
              <Image src="/sindh-bakery-mark.png" alt="" width={134} height={135} />
            </div>
            <h2 className="lp-card-title">Welcome back</h2>
            <p className="lp-card-sub">Sign in with the account you were given. You will only see the tabs assigned to you.</p>

            <label className="lp-field">
              <span>Email</span>
              <div className="lp-input">
                <Mail className="size-4" />
                <input
                  type="email"
                  autoComplete="username"
                  placeholder="you@company.com"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoFocus
                />
              </div>
            </label>

            <label className="lp-field">
              <span>Password</span>
              <div className="lp-input">
                <Lock className="size-4" />
                <input
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="••••••••••••"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  className="lp-eye"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((v) => !v)}
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </label>

            {error && (
              <p role="alert" className="lp-error">
                {error}
              </p>
            )}

            <button type="submit" className="lp-submit" disabled={busy || !email || !password}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : null}
              <span>{busy ? "Signing in…" : "Sign in"}</span>
              {!busy && <ArrowRight className="size-4 lp-submit-arrow" />}
            </button>

            <div className="lp-tabs">
              {["Sales", "Warehouse", "Stock", "HR", "Accounts"].map((t) => (
                <span key={t}>{t}</span>
              ))}
            </div>
          </form>

          <p className="lp-meta">
            <ShieldCheck className="size-3.5" /> Read-only on ERPNext · Role-based tabs · Confidential company data
          </p>
        </section>
      </div>
    </main>
  );
}
