"use client";

import { useEffect, useRef, useState } from "react";

import { AnswerView } from "@/components/AnswerView";
import { ChangesPanel } from "@/components/ChangesPanel";
import { DisclaimerGate } from "@/components/DisclaimerGate";
import { ProfileDialog, profileSummary } from "@/components/ProfileDialog";
import { SettingsBar } from "@/components/SettingsBar";
import { TracePanel } from "@/components/TracePanel";
import { fetchOptions, streamChat } from "@/lib/api";
import { download, loadConversation, saveConversation, toCsv, toJson, toMarkdown } from "@/lib/conversation";
import type { ChatEvent, FounderProfile, Options, Settings, Turn } from "@/lib/types";

const FALLBACK_DISCLAIMER =
  "This is general legal information, not legal advice. It does not replace consultation with a qualified lawyer.";
const MAX_CHARS = 2000;
const PROFILE_KEY = "flg-founder-profile-v1";

function loadProfile(): FounderProfile | null {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    return raw ? (JSON.parse(raw) as FounderProfile) : null;
  } catch {
    return null;
  }
}

function storeProfile(profile: FounderProfile | null) {
  try {
    if (profile) localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
    else localStorage.removeItem(PROFILE_KEY);
  } catch {}
}


function applyEvent(turn: Turn, event: ChatEvent): Turn {
  switch (event.type) {
    case "progress":
      return { ...turn, progress: [...turn.progress, event] };
    case "retrieval":
      return { ...turn, searches: [...turn.searches, event] };
    case "token":
      return { ...turn, draft: turn.draft + event.text };
    case "answer":
      return { ...turn, answer: event };
    case "guard":
      return { ...turn, guard: event };
    case "tool":
      return { ...turn, tools: [...turn.tools, event] };
    case "error":
      return { ...turn, status: "error", error: event.message };
    case "done":
      return turn.status === "error" ? turn : { ...turn, status: "done" };
  }
}

export default function Home() {
  const [options, setOptions] = useState<Options | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const [question, setQuestion] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [editingProfile, setEditingProfile] = useState(false);
  const [showChanges, setShowChanges] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchOptions()
      .then((o) => {
        setOptions(o);
        setSettings({
          strategy: o.default_strategy,
          answerModel: o.answer_models[0]?.id ?? "",
          answeringMode: "single_pass",
          jurisdictions: [],
          profile: loadProfile(),
        });
        setTurns((current) => (current.length ? current : loadConversation()));
      })
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  const busy = turns.some((t) => t.status === "streaming");
  const trimmed = question.trim();
  const tooLong = trimmed.length > MAX_CHARS;

  async function ask(text: string) {
    if (!settings || busy || !text.trim() || text.trim().length > MAX_CHARS) return;
    const turn: Turn = {
      id: crypto.randomUUID(),
      question: text.trim(),
      settings,
      status: "streaming",
      progress: [],
      searches: [],
      tools: [],
      draft: "",
    };
    const history = turns;
    setTurns((ts) => [...ts, turn]);
    setSelected(turn.id);
    setFocus(null);
    setQuestion("");
    const update = (event: ChatEvent) =>
      setTurns((ts) => ts.map((t) => (t.id === turn.id ? applyEvent(t, event) : t)));

    abort.current = new AbortController();
    try {
      await streamChat(turn.question, settings, history, update, abort.current.signal);
      setTurns((ts) => {
        const next = ts.map((t) => (t.id === turn.id && t.status === "streaming" ? { ...t, status: "done" as const } : t));
        saveConversation(next);
        return next;
      });
    } catch (e) {
      const message = (e as Error).name === "AbortError" ? "Stopped." : (e as Error).message;
      update({ type: "error", message });
    }
  }

  const disclaimer = options?.disclaimer ?? FALLBACK_DISCLAIMER;
  const selectedTurn = turns.find((t) => t.id === selected) ?? turns.at(-1);

  return (
    <div className="flex min-h-screen flex-col">
      <DisclaimerGate disclaimer={disclaimer} />
      {showChanges && <ChangesPanel onClose={() => setShowChanges(false)} />}
      {editingProfile && settings && (
        <ProfileDialog profile={settings.profile} onClose={() => setEditingProfile(false)}
          onSave={(profile) => { storeProfile(profile); setSettings({ ...settings, profile }); }} />
      )}

      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-7xl items-baseline justify-between gap-4 px-4 py-3">
          <h1 className="font-serif text-2xl">
            Founder Legal Guide <span className="text-accent">§</span>
          </h1>
          <div className="flex items-baseline gap-4">
            <p className="hidden text-sm text-ink-soft md:block">EU · Germany · US — for tech &amp; AI founders</p>
            <button type="button" onClick={() => setShowChanges(true)} className="text-sm text-accent underline">
              What changed
            </button>
            <a href="/dashboard" className="text-sm text-accent underline">Dashboard</a>
          </div>
        </div>
        <p role="note" className="bg-warn-soft px-4 py-1.5 text-center text-sm font-medium text-warn">
          {disclaimer}
        </p>
        {options?.demo_notice && (
          <p role="status" className="bg-accent-soft px-4 py-1.5 text-center text-sm text-accent">
            {options.demo_notice}
          </p>
        )}
      </header>

      <main className="mx-auto grid w-full max-w-7xl flex-1 gap-6 px-4 py-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <section className="flex min-w-0 flex-col gap-4">
          {loadError && (
            <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              Could not load settings: {loadError}
            </p>
          )}

          {turns.length === 0 && (
            <div className="rounded-lg border border-dashed border-line p-6">
              <h2 className="font-serif text-xl">What do you want to know?</h2>
              {settings && (
                <button type="button" onClick={() => setEditingProfile(true)}
                  className="mt-3 w-full rounded-md border border-accent bg-accent-soft px-3 py-2 text-left text-sm text-accent">
                  {settings.profile
                    ? `Your Founder Profile: ${profileSummary(settings.profile)} (edit)`
                    : "Start with your Founder Profile: a few quick questions so answers focus on the law that applies to you."}
                </button>
              )}
              <p className="mt-1 text-sm text-ink-soft">
                Ask in English or German. Answers cite the law and official guidance they rely on.
              </p>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {(options?.examples ?? []).map((example) => (
                  <button key={example} onClick={() => ask(example)} disabled={!settings}
                    className="rounded-md border border-line bg-surface px-3 py-2 text-left text-sm hover:border-accent">
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm print:hidden">
              <span className="text-ink-soft">Export:</span>
              <button onClick={() => download("founder-legal-guide.json", toJson(turns), "application/json")} className="text-accent underline">JSON</button>
              <button onClick={() => download("founder-legal-guide.md", toMarkdown(turns), "text/markdown")} className="text-accent underline">Markdown</button>
              <button onClick={() => download("founder-legal-guide.csv", toCsv(turns), "text/csv")} className="text-accent underline">CSV</button>
              <button onClick={() => window.print()} className="text-accent underline">PDF (print)</button>
              <button onClick={() => { setTurns([]); saveConversation([]); }} disabled={busy}
                className="ml-auto text-ink-soft underline">New conversation</button>
            </div>
          )}

          {turns.map((turn) => (
            <AnswerView key={turn.id} turn={turn} selected={turn.id === selectedTurn?.id}
              onSelect={() => setSelected(turn.id)} onCite={setFocus} />
          ))}
        </section>

        <aside className="min-w-0 print:hidden lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
          <h2 className="mb-3 font-serif text-lg">How this answer was found</h2>
          <TracePanel turn={selectedTurn} focus={focus} />
        </aside>
      </main>

      <footer className="sticky bottom-0 print:hidden border-t border-line bg-surface/95 backdrop-blur">
        <form className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-3"
          onSubmit={(e) => { e.preventDefault(); ask(question); }}>
          {options && settings && (
            <>
              <button type="button" onClick={() => setShowSettings((v) => !v)} aria-expanded={showSettings}
                className="self-start text-xs text-ink-soft underline lg:hidden">
                {showSettings ? "Hide settings" : `Settings: ${settings.strategy} · ${settings.answeringMode === "agentic" ? "Agentic" : "Single-pass"}`}
              </button>
              <div className={showSettings ? "block" : "hidden lg:block"}>
                <SettingsBar options={options} settings={settings} onChange={setSettings} disabled={busy}
                  onEditProfile={() => setEditingProfile(true)} />
              </div>
            </>
          )}
          <div className="flex gap-2">
            <label htmlFor="question" className="sr-only">Your question</label>
            <textarea id="question" value={question} rows={2} placeholder="Ask about company law, data protection, AI regulation…"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(question); } }}
              className="flex-1 resize-none rounded-md border border-line bg-paper px-3 py-2 focus:border-accent focus:outline-none" />
            {busy ? (
              <button type="button" onClick={() => abort.current?.abort()}
                className="rounded-md border border-line px-4 font-medium">Stop</button>
            ) : (
              <button type="submit" disabled={!settings || !trimmed || tooLong}
                className="rounded-md bg-accent px-4 font-medium text-surface disabled:opacity-40">Ask</button>
            )}
          </div>
          <p className={`text-xs ${tooLong ? "text-danger" : "text-ink-soft"}`}>
            {trimmed.length}/{MAX_CHARS} characters · Don&apos;t include personal data about others.
          </p>
        </form>
      </footer>
    </div>
  );
}
