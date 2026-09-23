import {
  ArrowRight,
  Boxes,
  Camera,
  LineChart,
  Mic,
  Target,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";

import { ThemeToggle } from "@/components/ThemeToggle";

/** The public landing page. */
export default function Home() {
  return (
    <main>
      <nav className="marketing-nav">
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
          <span>
            <span className="sidebar__wordmark">ShopperMind</span>
            <p className="sidebar__tagline">Shopper intelligence</p>
          </span>
        </span>
        <span style={{ display: "flex", gap: "var(--s-3)", alignItems: "center" }}>
          <ThemeToggle />
          <Link href="/login" className="btn btn--ghost">Sign in</Link>
          <Link href="/register" className="btn">Start free trial</Link>
        </span>
      </nav>

      <header className="hero">
        <div className="hero__inner">
          <p className="u-eyebrow">AI shopper intelligence platform</p>
          <h1
            className="u-display"
            style={{ fontSize: "var(--t-hero)", margin: "var(--s-4) 0", maxWidth: "20ch" }}
          >
            From &ldquo;Why did sales fall?&rdquo; to &ldquo;What should we do next?&rdquo;
          </h1>
          <p className="u-lede">
            An always-on AI shopper intelligence platform for quick service restaurants and
            retail. It turns customer data into business decisions, in plain language.
          </p>
          <p style={{ marginTop: "var(--s-6)", display: "flex", gap: "var(--s-3)", flexWrap: "wrap" }}>
            <Link href="/register" className="btn">
              Create a workspace <ArrowRight size={15} style={{ verticalAlign: "-2px" }} />
            </Link>
            <Link href="/login" className="btn btn--ghost">Sign in</Link>
          </p>
        </div>
      </header>

      <section className="wrap" style={{ paddingTop: "var(--s-7)" }}>
        <p className="u-eyebrow">Where most dashboards stop, ShopperMind continues</p>
        <div className="grid-3" style={{ marginTop: "var(--s-5)" }}>
          {[
            [<LineChart key="i" size={20} />, "Reason",
             "Most platforms report what happened. ShopperMind separates volume from basket size, checks the category against the item, and names the factors the data actually supports."],
            [<Target key="i" size={20} />, "Act",
             "Every finding ends in something ownable: who does it, by when, and what it is expected to be worth. A number with no recommendation is not an insight."],
            [<Boxes key="i" size={20} />, "Measure",
             "The loop closes. Record what you did and what happened, and the platform scores its own hit rate rather than asking you to take it on trust."],
          ].map(([icon, title, body], i) => (
            <div key={i} className="liquid-card" style={{ padding: "var(--s-5)" }}>
              <span style={{ color: "var(--accent-2)" }}>{icon}</span>
              <h2 className="section__title" style={{ margin: "var(--s-3) 0" }}>{title}</h2>
              <p style={{ color: "var(--text-muted)", margin: 0 }}>{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="wrap section">
        <p className="u-eyebrow">The difference</p>
        <div className="grid-2" style={{ marginTop: "var(--s-4)" }}>
          <div className="liquid-card" style={{ padding: "var(--s-5)" }}>
            <p className="u-eyebrow u-eyebrow--muted">A typical analytics platform says</p>
            <p style={{ marginTop: "var(--s-3)", color: "var(--text-muted)" }}>
              Sales declined 7%.
            </p>
          </div>
          <div
            className="liquid-card"
            style={{ padding: "var(--s-5)", borderColor: "var(--accent-ring)" }}
          >
            <p className="u-eyebrow">ShopperMind says</p>
            <p style={{ marginTop: "var(--s-3)", color: "var(--text)" }}>
              Sales declined 7%. Order count moved −8.7% while average basket held, so this
              is a traffic problem, not a merchandising one. The decline concentrates in the
              evening daypart. Put spend behind that daypart before touching price, and
              re-measure both components in two weeks.
            </p>
          </div>
        </div>
      </section>

      <section className="wrap">
        <div className="band">
          <p className="u-eyebrow">Fourteen modules, one picture of the shopper</p>
          <h2
            className="u-display"
            style={{ fontSize: "var(--t-title)", margin: "var(--s-3) 0 var(--s-5)" }}
          >
            Five questions, answered continuously.
          </h2>
          <div className="grid-3">
            {[
              ["Who is buying", "Customer profiling, store intelligence."],
              ["What are they buying", "Purchase behaviour, menu intelligence, basket analysis."],
              ["Why are they buying", "Sentiment intelligence, price sensitivity."],
              ["What is stopping them", "Voice of customer, competitor intelligence, churn intelligence, in-store vision."],
              ["What should we offer next", "Next best offer, campaign intelligence, trend detection."],
              ["And before you commit", "The Shopper Simulator estimates the outcome from your own history."],
            ].map(([q, a]) => (
              <div key={q} style={{ marginBottom: "var(--s-4)" }}>
                <p className="u-eyebrow">{q}</p>
                <p style={{ color: "var(--text-muted)", margin: "var(--s-2) 0 0" }}>{a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="wrap section">
        <div className="grid-2">
          <div className="liquid-card" style={{ padding: "var(--s-5)" }}>
            <span style={{ color: "var(--accent-2)" }}><Camera size={20} /></span>
            <p className="u-eyebrow" style={{ marginTop: "var(--s-3)" }}>In-store cameras</p>
            <h2 className="section__title" style={{ margin: "var(--s-2) 0 var(--s-3)" }}>
              The one number neither the POS nor the camera can produce alone
            </h2>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              Footfall from cameras, orders from the POS. Together they give conversion — so
              when a store is down you can tell whether fewer people came in, or the same
              people came in and left without buying. Events are anonymous aggregates:
              counts, dwell seconds, queue length. No face templates, no identity, no join
              back to the customer record.
            </p>
          </div>
          <div className="liquid-card" style={{ padding: "var(--s-5)" }}>
            <span style={{ color: "var(--accent-2)" }}><Mic size={20} /></span>
            <p className="u-eyebrow" style={{ marginTop: "var(--s-3)" }}>Voice</p>
            <h2 className="section__title" style={{ margin: "var(--s-2) 0 var(--s-3)" }}>
              Ask it out loud, between meetings
            </h2>
            <p style={{ color: "var(--text-muted)", margin: 0 }}>
              Speech in and speech out through Azure AI Speech, in English and six Indian
              languages. A spoken answer is written for the ear — one number, one reason,
              one action, with the detail left on screen.
            </p>
          </div>
        </div>
      </section>

      <footer className="appfooter" style={{ marginTop: "var(--s-8)" }}>
        <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-muted)" }}>
          ShopperMind{" "}
          <span style={{ color: "var(--text-faint)", fontWeight: 400 }}>
            · Powered by RLAI
          </span>
        </span>
        <span className="u-mono" style={{ color: "var(--text-faint)" }}>© 2026 RLAI Inc.</span>
      </footer>
    </main>
  );
}
