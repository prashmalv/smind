"use client";

/**
 * Theme state. Dark is the default look, matching RLAI SupplyMind.
 *
 * The class is also applied pre-paint by an inline script in the root layout — this
 * provider keeps React in sync and persists the choice, but it is not what prevents the
 * flash of the wrong theme on first load.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import type { Theme } from "./viz";

const KEY = "sm_theme";

interface ThemeCtx {
  theme: Theme;
  toggle: () => void;
  setTheme: (t: Theme) => void;
}

const Ctx = createContext<ThemeCtx | null>(null);

function apply(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.setAttribute("data-theme", theme);
  root.style.colorScheme = theme;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Server render has no localStorage, so start on the default and correct on mount.
  // The inline script has already painted the right theme by then.
  const [theme, setThemeState] = useState<Theme>("dark");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(KEY) as Theme | null;
      if (saved === "light" || saved === "dark") setThemeState(saved);
    } catch {
      /* private browsing, blocked storage — the default stands */
    }
  }, []);

  useEffect(() => {
    apply(theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* nothing to do — the theme still applies for this session */
    }
  }, [theme]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const toggle = useCallback(
    () => setThemeState((t) => (t === "dark" ? "light" : "dark")),
    [],
  );

  return <Ctx.Provider value={{ theme, toggle, setTheme }}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  // Pages outside the provider (login, landing) still need to read a value.
  return ctx ?? { theme: "dark", toggle: () => {}, setTheme: () => {} };
}
