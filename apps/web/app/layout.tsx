import type { Metadata } from "next";

import { ThemeProvider } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "ShopperMind AI — Understand. Predict. Personalise. Act.",
  description:
    "An always-on AI shopper intelligence platform for quick service restaurants and "
    + "retail. It turns customer data into business decisions, in plain language.",
};

/**
 * Applied before first paint so the page never flashes the wrong theme. It has to be
 * inline and synchronous — a React effect runs after the browser has already painted.
 */
const THEME_BOOTSTRAP = `
(function () {
  try {
    var t = localStorage.getItem('sm_theme') || 'dark';
    if (t === 'dark') document.documentElement.classList.add('dark');
    document.documentElement.setAttribute('data-theme', t);
    document.documentElement.style.colorScheme = t;
  } catch (e) {
    document.documentElement.classList.add('dark');
  }
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
