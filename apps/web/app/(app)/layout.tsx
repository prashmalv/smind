"use client";

/**
 * The authenticated shell — collapsible sidebar, sticky header, footer. Matches the
 * RLAI SupplyMind chrome so the two products feel like one suite.
 *
 * Navigation is grouped by what the person came to do, not by which module produced the
 * data: a marketing head thinks "who is at risk", not "churn_intelligence".
 */

import {
  Boxes,
  Camera,
  Database,
  LayoutDashboard,
  Lightbulb,
  LogOut,
  Menu,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { BrandLogo } from "@/components/BrandLogo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { clearSession, getTenant, getToken, getUser, type Tenant, type User } from "@/lib/api";

type NavItem = { href: string; label: string; icon: ReactNode };

const PRIMARY: NavItem[] = [
  { href: "/command", label: "Command center", icon: <LayoutDashboard size={18} /> },
  { href: "/ask", label: "Ask ShopperMind", icon: <MessageSquareText size={18} /> },
  { href: "/insights", label: "Insights", icon: <Lightbulb size={18} /> },
  { href: "/modules", label: "Modules", icon: <Boxes size={18} /> },
];

const ACT: NavItem[] = [
  { href: "/customers", label: "Customers & offers", icon: <Users size={18} /> },
  { href: "/simulator", label: "Shopper Simulator", icon: <SlidersHorizontal size={18} /> },
];

const STORES: NavItem[] = [
  { href: "/cameras", label: "In-store vision", icon: <Camera size={18} /> },
  { href: "/data", label: "Data sources", icon: <Database size={18} /> },
  { href: "/settings", label: "Settings", icon: <Settings size={18} /> },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setTenant(getTenant());
    setUser(getUser());
    try {
      setCollapsed(localStorage.getItem("sm_sidebar") === "collapsed");
    } catch {
      /* blocked storage — the default stands */
    }
    setReady(true);
  }, [router]);

  const toggleCollapse = () =>
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem("sm_sidebar", next ? "collapsed" : "open");
      } catch {
        /* nothing to do */
      }
      return next;
    });

  if (!ready) {
    return <p className="loading" style={{ padding: "var(--s-8)" }}>Loading your workspace…</p>;
  }

  const Group = ({ items, label }: { items: NavItem[]; label?: string }) => (
    <div className="sidebar__group">
      {label && !collapsed && <p className="sidebar__grouplabel">{label}</p>}
      {label && collapsed && <div className="sidebar__groupdivider" />}
      {items.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className="sidebar__link"
          aria-current={pathname === item.href ? "page" : undefined}
          title={collapsed ? item.label : undefined}
          onClick={() => setMobileOpen(false)}
        >
          {item.icon}
          <span>{item.label}</span>
        </Link>
      ))}
    </div>
  );

  return (
    <div className="shell">
      <nav
        className="sidebar"
        aria-label="Main"
        data-collapsed={collapsed}
        data-mobile-open={mobileOpen}
      >
        <div className="sidebar__brand">
          {/* The wordmark already says ShopperMind, so nothing is repeated beside it. */}
          <Link href="/command" aria-label="ShopperMind — command center">
            <BrandLogo height={collapsed ? 30 : 24} mark={collapsed} priority />
          </Link>
        </div>

        <div className="sidebar__nav scrollbar-hide">
          <Group items={PRIMARY} />
          <Group items={ACT} label="Act" />
          <Group items={STORES} label="Stores" />
        </div>

        <button className="sidebar__collapse" onClick={toggleCollapse}>
          {collapsed ? <PanelLeftOpen size={18} /> : <><PanelLeftClose size={18} /><span>Collapse</span></>}
        </button>
      </nav>

      {mobileOpen && (
        <div className="sidebar-scrim" onClick={() => setMobileOpen(false)} aria-hidden />
      )}

      <div className="main">
        <header className="topbar">
          <button
            className="icon-btn only-mobile"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu size={18} />
          </button>
          <span className="topbar__spacer" />
          <span className="u-mono" style={{ color: "var(--text-faint)" }}>
            {tenant?.plan} plan
          </span>
          <ThemeToggle />
          <UserMenu user={user} onSignOut={() => { clearSession(); router.push("/login"); }} />
        </header>

        <main style={{ flex: 1 }}>{children}</main>

        <footer className="appfooter">
          <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-muted)" }}>
            ShopperMind{" "}
            <span style={{ color: "var(--text-faint)", fontWeight: 400 }}>
              · Powered by RLAI
            </span>
          </span>
          <span className="u-mono" style={{ color: "var(--text-faint)" }}>
            © 2026 RLAI Inc.
          </span>
        </footer>
      </div>
    </div>
  );
}

function UserMenu({ user, onSignOut }: { user: User | null; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const initials = (user?.full_name || user?.email || "U")
    .split(/[\s@.]+/)
    .map((s) => s[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div style={{ position: "relative" }} ref={ref}>
      <button
        className="avatar"
        onClick={() => setOpen((v) => !v)}
        aria-label="Account menu"
        aria-expanded={open}
      >
        {initials}
      </button>
      {open && (
        <div className="menu">
          <div className="menu__head">
            <p style={{ margin: 0, fontSize: "14px", color: "var(--text-strong)" }}>
              {user?.full_name}
            </p>
            <p style={{ margin: 0, fontSize: "11px", color: "var(--text-faint)" }}>
              {user?.email} · {user?.role}
            </p>
          </div>
          <button className="menu__item" onClick={onSignOut}>
            <LogOut size={14} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
