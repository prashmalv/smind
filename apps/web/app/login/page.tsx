"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { ApiError, api, saveSession, type Tenant, type User } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenantSlug, setTenantSlug] = useState("");
  // Populated when one email belongs to several workspaces — the API returns the list
  // rather than guessing which one was meant.
  const [workspaces, setWorkspaces] = useState<{ slug: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ access_token: string; tenant: Tenant; user: User }>(
        "/api/v1/auth/login",
        {
          method: "POST",
          auth: false,
          body: { email, password, tenant_slug: tenantSlug || null },
        },
      );
      saveSession(res.access_token, res.tenant, res.user);
      router.push("/command");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const detail = err.detail as { workspaces?: { slug: string; name: string }[] };
        setWorkspaces(detail.workspaces ?? []);
        setError("This email belongs to more than one workspace. Choose one.");
      } else {
        setError("Email or password is incorrect.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <aside className="auth__aside">
        <div>
          <span style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <Image
              src="/rlailogo.png"
              alt="RLAI"
              width={436}
              height={222}
              className="brand-logo"
              priority
              unoptimized
            />
            <span className="sidebar__wordmark">ShopperMind</span>
          </span>
          <h1
            className="u-display"
            style={{ fontSize: "var(--t-title)", margin: "var(--s-6) 0 var(--s-4)", maxWidth: "14ch" }}
          >
            Understand. Predict. Personalise. Act.
          </h1>
          <p className="u-lede">
            An always-on consumer intelligence assistant for QSR and retail brands.
          </p>
        </div>
        <p className="u-eyebrow">AI shopper intelligence platform</p>
      </aside>

      <section className="auth__form">
        <div className="auth__form-inner">
          <div style={{ display: "flex", justifyContent: "flex-end",
                        marginBottom: "var(--s-4)" }}>
            <ThemeToggle />
          </div>
          <p className="u-eyebrow">Sign in</p>
          <h2 className="u-display" style={{ fontSize: "30px", margin: "var(--s-3) 0 var(--s-6)" }}>
            Welcome back
          </h2>

          <form onSubmit={submit}>
            <label className="field">
              <span className="field__label">Work email</span>
              <input
                className="input" type="email" required value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field__label">Password</span>
              <input
                className="input" type="password" required value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>

            {workspaces.length > 0 && (
              <label className="field">
                <span className="field__label">Workspace</span>
                <select
                  className="input" value={tenantSlug}
                  onChange={(e) => setTenantSlug(e.target.value)}
                  required
                >
                  <option value="">Choose a workspace…</option>
                  {workspaces.map((w) => (
                    <option key={w.slug} value={w.slug}>{w.name}</option>
                  ))}
                </select>
              </label>
            )}

            {error && <p className="error">{error}</p>}

            <button className="btn" type="submit" disabled={busy} style={{ width: "100%" }}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="hint" style={{ marginTop: "var(--s-5)" }}>
            No workspace yet? <Link href="/register">Create one</Link>
          </p>
        </div>
      </section>
    </main>
  );
}
