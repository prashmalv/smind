/**
 * Voice in and out.
 *
 * Azure AI Speech is used when the workspace has it configured — the server mints a
 * ten-minute token so the subscription key never reaches the browser. Otherwise this
 * falls back to the Web Speech API, which every modern browser ships. The fallback is
 * why the voice button is never disabled just because Azure is not wired up yet.
 */

import { API_URL, getToken } from "./api";

export type VoiceConfig = {
  enabled: boolean;
  provider: "azure-speech" | "browser";
  default_locale: string;
  default_voice: string;
  locales: string[];
  sample_questions: string[];
};

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: unknown) => void) | null;
  onend: (() => void) | null;
};

function recognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition) as
    (new () => SpeechRecognitionLike) | null;
}

export function speechSupported(): boolean {
  return recognitionCtor() !== null;
}

/** Start dictation. Returns a stop function. */
export function listen(
  locale: string,
  onTranscript: (text: string, final: boolean) => void,
  onEnd: () => void,
): () => void {
  const Ctor = recognitionCtor();
  if (!Ctor) {
    onEnd();
    return () => {};
  }
  const rec = new Ctor();
  rec.lang = locale;
  rec.continuous = false;
  rec.interimResults = true;

  rec.onresult = (e) => {
    let text = "";
    for (let i = 0; i < e.results.length; i += 1) text += e.results[i][0].transcript;
    // The last result batch is the settled one; anything before it can still change.
    onTranscript(text, false);
  };
  rec.onerror = () => onEnd();
  rec.onend = () => onEnd();

  try {
    rec.start();
  } catch {
    onEnd();
  }
  return () => { try { rec.stop(); } catch { /* already stopped */ } };
}

/**
 * Speak an answer. Tries the server (Azure Speech, better prosody and Indian-English
 * voices) and falls back to the browser's own synthesiser.
 */
export async function speak(text: string, locale = "en-IN"): Promise<void> {
  const token = getToken();
  if (token) {
    try {
      const res = await fetch(`${API_URL}/api/v1/copilot/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ text, locale }),
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        await audio.play();
        audio.onended = () => URL.revokeObjectURL(url);
        return;
      }
    } catch {
      /* fall through to the browser synthesiser */
    }
  }

  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = locale;
    utter.rate = 0.96;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
  }
}

export function stopSpeaking() {
  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}
