"use client";

/**
 * Self-service signup. Anyone can create a workspace — that is the point of the
 * platform — and the demo estate is seeded by default so the product is explorable
 * before a POS connector exists.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { BrandLogo } from "@/components/BrandLogo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ApiError, api, saveSession, type Tenant, type User } from "@/lib/api";

const VERTICALS = [
  ["qsr", "Quick service restaurant"],
  ["cafe", "Café / coffee chain"],
  ["retail", "Retail chain"],
  ["grocery", "Grocery / supermarket"],
  ["pharmacy", "Pharmacy"],
  ["fashion", "Fashion / apparel"],
];

const COUNTRIES = [
  ["IN", "India", "INR", "Asia/Kolkata"],
  ["AE", "United Arab Emirates", "AED", "Asia/Dubai"],
  ["GB", "United Kingdom", "GBP", "Europe/London"],
  ["US", "United States", "USD", "America/New_York"],
];

export default function Register() {
  const router = useRouter();
  const [form, setForm] = useState({
    company_name: "",
    vertical: "qsr",
    country: "IN",
    full_name: "",
    email: "",
    password: "",
    job_title: "",
    seed_demo_data: true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (key: string, value: string | boolean) =>
    setForm((f) => ({ ...f, [key]: value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const country = COUNTRIES.find((c) => c[0] === form.country)!;
    try {
      const res = await api<{ access_token: string; tenant: Tenant; user: User }>(
        "/api/v1/auth/register",
        {
          method: "POST",
          auth: false,
          body: { ...form, currency: country[2], timezone: country[3] },
        },
      );
      saveSession(res.access_token, res.tenant, res.user);
      router.push("/command");
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail : null;
      setError(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d: { msg?: string }) => d.msg ?? "").join(" · ")
            : "Could not create the workspace. Check the details and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <aside className="auth__aside">
        <div>
          <BrandLogo height={34} priority />
          <h1
            className="u-display"
            style={{ fontSize: "var(--t-title)", margin: "var(--s-6) 0 var(--s-4)", maxWidth: "14ch" }}
          >
            Your workspace comes with a working estate.
          </h1>
          <p className="u-lede">
            Sign up and the platform seeds a realistic multi-store dataset — orders,
            reviews, campaigns and camera feeds — so every module has something true to
            find on the first screen. Connect your own POS whenever you are ready.
          </p>
        </div>
        <div>
          <p className="u-eyebrow">Included in the trial</p>
          <p style={{ marginTop: "var(--s-3)" }}>
            3 stores · 3 cameras · 5 seats · all fourteen intelligence modules · the
            Shopper Simulator · voice.
          </p>
        </div>
      </aside>

      <section className="auth__form">
        <div className="auth__form-inner">
          <div style={{ display: "flex", justifyContent: "flex-end",
                        marginBottom: "var(--s-4)" }}>
            <ThemeToggle />
          </div>
          <p className="u-eyebrow">Create a workspace</p>
          <h2 className="u-display" style={{ fontSize: "30px", margin: "var(--s-3) 0 var(--s-6)" }}>
            Start your 30-day trial
          </h2>

          <form onSubmit={submit}>
            <label className="field">
              <span className="field__label">Company name</span>
              <input
                className="input" required minLength={2} value={form.company_name}
                onChange={(e) => set("company_name", e.target.value)}
                placeholder="Crave Kitchens"
              />
            </label>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--s-4)" }}>
              <label className="field">
                <span className="field__label">Business type</span>
                <select
                  className="input" value={form.vertical}
                  onChange={(e) => set("vertical", e.target.value)}
                >
                  {VERTICALS.map(([v, label]) => (
                    <option key={v} value={v}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field__label">Country</span>
                <select
                  className="input" value={form.country}
                  onChange={(e) => set("country", e.target.value)}
                >
                  {COUNTRIES.map(([c, label]) => (
                    <option key={c} value={c}>{label}</option>
                  ))}
                </select>
              </label>
            </div>

            <label className="field">
              <span className="field__label">Your name</span>
              <input
                className="input" required value={form.full_name}
                onChange={(e) => set("full_name", e.target.value)}
              />
            </label>

            <label className="field">
              <span className="field__label">Work email</span>
              <input
                className="input" type="email" required value={form.email}
                onChange={(e) => set("email", e.target.value)}
              />
            </label>

            <label className="field">
              <span className="field__label">Job title</span>
              <input
                className="input" value={form.job_title}
                onChange={(e) => set("job_title", e.target.value)}
                placeholder="Head of Marketing"
              />
            </label>

            <label className="field">
              <span className="field__label">Password</span>
              <input
                className="input" type="password" required minLength={10}
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
              />
              <span className="hint">
                At least 10 characters, mixing letters with numbers or symbols.
              </span>
            </label>

            <label
              className="field"
              style={{ display: "flex", gap: "var(--s-3)", alignItems: "flex-start" }}
            >
              <input
                type="checkbox" checked={form.seed_demo_data}
                onChange={(e) => set("seed_demo_data", e.target.checked)}
                style={{ marginTop: "6px", width: "18px", height: "18px" }}
              />
              <span>
                <span className="field__label" style={{ marginBottom: 0 }}>
                  Seed a demo estate
                </span>
                <span className="hint">
                  Ten stores, 75 days of orders, reviews, campaigns and camera feeds. Takes
                  a few seconds.
                </span>
              </span>
            </label>

            {error && <p className="error">{error}</p>}

            <button className="btn" type="submit" disabled={busy} style={{ width: "100%" }}>
              {busy ? "Creating your workspace…" : "Create workspace"}
            </button>
          </form>

          <p className="hint" style={{ marginTop: "var(--s-5)" }}>
            Already have a workspace? <Link href="/login">Sign in</Link>
          </p>
        </div>
      </section>
    </main>
  );
}
