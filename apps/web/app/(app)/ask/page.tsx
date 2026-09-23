"use client";

/**
 * Ask ShopperMind — text and voice.
 *
 * Each answer carries its provenance: which modules ran, how long it took, and whether
 * the reasoning came from Azure OpenAI or the local reasoner. That strip is not
 * decoration — a category head who cannot see where a number came from will not act on it.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

import { Chart } from "@/components/Chart";
import { Finding, type FindingT } from "@/components/Finding";
import { PeriodPicker } from "@/components/PeriodPicker";
import { api, getTenant } from "@/lib/api";
import { listen, speak, speechSupported, stopSpeaking, type VoiceConfig } from "@/lib/voice";

type Answer = {
  conversation_id: string;
  answer: string;
  modules_used: string[];
  findings: FindingT[];
  charts: { name: string; points: { label: string; value: number }[]; unit: string }[];
  followups: string[];
  latency_ms: number;
  engine: string;
};

type Turn =
  | { role: "user"; text: string; voice: boolean }
  | { role: "assistant"; text: string; data: Answer };

function AskInner() {
  const params = useSearchParams();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [days, setDays] = useState(30);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [voice, setVoice] = useState<VoiceConfig | null>(null);
  const [listening, setListening] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(false);
  const stopListening = useRef<() => void>(() => {});
  const endRef = useRef<HTMLDivElement>(null);
  const currency = getTenant()?.currency ?? "INR";

  useEffect(() => {
    api<VoiceConfig>("/api/v1/voice/config").then(setVoice).catch(() => setVoice(null));
  }, []);

  const send = useCallback(
    async (question: string, spoken = false) => {
      const q = question.trim();
      if (!q || busy) return;
      setBusy(true);
      setDraft("");
      setTurns((t) => [...t, { role: "user", text: q, voice: spoken }]);
      try {
        const res = await api<Answer>("/api/v1/copilot/ask", {
          method: "POST",
          body: {
            question: q,
            conversation_id: conversationId,
            period_days: days,
            is_voice: spoken,
          },
        });
        setConversationId(res.conversation_id);
        setTurns((t) => [...t, { role: "assistant", text: res.answer, data: res }]);
        if (spoken || speakReplies) {
          speak(res.answer, voice?.default_locale ?? "en-IN");
        }
      } catch {
        setTurns((t) => [
          ...t,
          {
            role: "assistant",
            text: "I could not reach the intelligence layer for that question. "
              + "The API may be down — the numbers on screen are never guessed, so I would "
              + "rather say nothing than invent one.",
            data: {
              conversation_id: "", answer: "", modules_used: [], findings: [],
              charts: [], followups: [], latency_ms: 0, engine: "error",
            },
          },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [busy, conversationId, days, speakReplies, voice],
  );

  // A question handed over from the command center arrives as ?q=
  const seeded = useRef(false);
  useEffect(() => {
    const q = params.get("q");
    if (q && !seeded.current) {
      seeded.current = true;
      send(q);
    }
  }, [params, send]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  function toggleMic() {
    if (listening) {
      stopListening.current();
      setListening(false);
      return;
    }
    stopSpeaking();
    setListening(true);
    let heard = "";
    stopListening.current = listen(
      voice?.default_locale ?? "en-IN",
      (text) => { heard = text; setDraft(text); },
      () => {
        setListening(false);
        if (heard.trim()) send(heard, true);
      },
    );
  }

  const micAvailable = speechSupported() && voice?.enabled !== false;

  return (
    <div className="page">
      <header className="page__head">
        <p className="u-eyebrow">Ask ShopperMind</p>
        <h1 className="u-display">An intelligence, not another dashboard</h1>
        <p className="u-lede">
          Ask in plain language and get an explanation with a recommendation. Every figure
          comes from a module run against your data — nothing is estimated to fill a gap.
        </p>
      </header>

      <div className="filters">
        <PeriodPicker value={days} onChange={setDays} />
        <button
          className="btn btn--ghost btn--sm"
          aria-pressed={speakReplies}
          onClick={() => { setSpeakReplies((s) => !s); stopSpeaking(); }}
        >
          {speakReplies ? "Speaking replies" : "Speak replies"}
        </button>
        {voice && (
          <span className="u-mono" style={{ color: "var(--ink-3)" }}>
            voice: {voice.provider === "azure-speech" ? "Azure AI Speech" : "browser"}
          </span>
        )}
      </div>

      <div className="ask">
        <div>
          <div className="thread">
            {turns.length === 0 && (
              <div className="empty">
                <p className="u-eyebrow">Try one of these</p>
                <p style={{ marginTop: "var(--s-3)" }}>
                  Ask why something moved, not just what it is. The platform is built to
                  answer the second question.
                </p>
              </div>
            )}

            {turns.map((turn, i) =>
              turn.role === "user" ? (
                <div className="turn turn--user" key={i}>
                  <p className="u-eyebrow u-eyebrow--muted">
                    You{turn.voice ? " · spoken" : ""}
                  </p>
                  <p className="turn__text" style={{ marginTop: "var(--s-2)" }}>{turn.text}</p>
                </div>
              ) : (
                <div className="turn" key={i}>
                  <p className="u-eyebrow">ShopperMind</p>
                  <p className="turn__text" style={{ marginTop: "var(--s-2)" }}>{turn.text}</p>

                  {turn.data.modules_used.length > 0 && (
                    <div className="turn__meta">
                      {turn.data.modules_used.map((m) => (
                        <Link key={m} href={`/modules/${m}`} className="chip">
                          {m.replace(/_/g, " ")}
                        </Link>
                      ))}
                      <span className="chip">{turn.data.latency_ms} ms</span>
                      <span className="chip">
                        {turn.data.engine === "azure-openai" ? "Azure OpenAI" : "local reasoner"}
                      </span>
                      <button
                        className="btn btn--ghost btn--sm"
                        onClick={() => speak(turn.text, voice?.default_locale ?? "en-IN")}
                      >
                        Play
                      </button>
                    </div>
                  )}

                  {turn.data.charts.slice(0, 2).map((c, ci) => (
                    <Chart
                      key={c.name}
                      title={c.name}
                      points={c.points}
                      unit={c.unit}
                      kind={c.points.length > 12 ? "line" : "bar"}
                      colorIndex={ci}
                    />
                  ))}

                  {turn.data.findings.slice(0, 2).map((f, fi) => (
                    <Finding key={fi} finding={f} currency={currency} />
                  ))}

                  {turn.data.followups.length > 0 && (
                    <div className="filters" style={{ marginTop: "var(--s-4)", marginBottom: 0 }}>
                      {turn.data.followups.map((q) => (
                        <button
                          key={q}
                          className="btn btn--ghost btn--sm"
                          onClick={() => send(q)}
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ),
            )}
            {busy && <p className="loading">Running the modules that hold the answer…</p>}
            <div ref={endRef} />
          </div>

          <form
            className="composer"
            onSubmit={(e) => { e.preventDefault(); send(draft); }}
          >
            <div className="composer__row">
              <textarea
                className="input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(draft);
                  }
                }}
                placeholder={listening ? "Listening…" : "Ask about sales, stores, customers, queues…"}
                rows={2}
                aria-label="Your question"
              />
              <button
                type="button"
                className="btn btn--ghost mic"
                aria-pressed={listening}
                aria-label={listening ? "Stop listening" : "Ask by voice"}
                onClick={toggleMic}
                disabled={!micAvailable}
                title={micAvailable ? "Ask by voice" : "Voice is not available in this browser"}
              >
                {listening ? "■" : "●"}
              </button>
              <button className="btn" type="submit" disabled={busy || !draft.trim()}>
                Ask
              </button>
            </div>
          </form>
        </div>

        <aside>
          <p className="u-eyebrow">Suggested questions</p>
          <div className="suggestions" style={{ marginTop: "var(--s-3)" }}>
            {(voice?.sample_questions ?? [
              "Why did sales fall this month?",
              "Which stores need attention?",
              "What are customers complaining about?",
              "What should we promote this weekend?",
              "Which customers are about to churn?",
            ]).map((q) => (
              <button key={q} className="suggestion" onClick={() => send(q)}>
                {q}
              </button>
            ))}
          </div>

          <p className="u-eyebrow" style={{ marginTop: "var(--s-6)" }}>How it answers</p>
          <p style={{ fontSize: "14px", marginTop: "var(--s-3)" }}>
            Three movements, always in this order: what happened, why it happened, and what
            to do. If a source is not connected, it says so rather than estimating.
          </p>
        </aside>
      </div>
    </div>
  );
}

export default function Ask() {
  return (
    <Suspense fallback={<p className="loading" style={{ padding: "var(--s-8)" }}>Loading…</p>}>
      <AskInner />
    </Suspense>
  );
}
