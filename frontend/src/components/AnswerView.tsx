"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Turn } from "@/lib/types";

/** Turns [n] into links the citation renderer recognises. */
function linkCitations(text: string): string {
  return text.replace(/\[(\d{1,3})\](?!\()/g, "[[$1]](#cite-$1)");
}

type Props = { turn: Turn; selected: boolean; onSelect: () => void; onCite: (n: number) => void };

export function AnswerView({ turn, selected, onSelect, onCite }: Props) {
  const text = turn.answer?.text ?? turn.draft;
  const invalid = new Set(turn.answer?.citations.invalid ?? []);
  const lastProgress = turn.progress.at(-1);

  return (
    <article onClick={onSelect}
      className={`rounded-lg border bg-surface p-5 transition ${selected ? "border-accent" : "border-line"}`}>
      <p className="font-serif text-lg">{turn.question}</p>
      <p className="mt-1 text-xs text-ink-soft">
        {turn.settings.answeringMode === "agentic" ? "Agentic" : "Single-pass"} · {turn.settings.strategy} ·{" "}
        {turn.settings.answerModel}
      </p>

      {turn.guard && turn.guard.triggers.length > 0 && (
        <div role="alert" className={`mt-3 rounded-md px-3 py-2 text-sm ${turn.guard.triggers.some((t) => t.urgent) ? "bg-danger-soft text-danger" : "bg-warn-soft text-warn"}`}>
          <p className="font-semibold">Talk to a lawyer</p>
          <ul className="mt-1 list-disc pl-5">
            {turn.guard.triggers.map((t) => <li key={t.id}>{t.label}{t.urgent && " (time-critical)"}</li>)}
          </ul>
        </div>
      )}
      {turn.guard && turn.guard.personal_data.length > 0 && (
        <p className="mt-3 rounded-md bg-accent-soft px-3 py-2 text-sm text-accent">
          We removed personal data ({turn.guard.personal_data.join(", ")}) from your question before it reached any model.
          Please don&apos;t share personal data about others.
        </p>
      )}
      {turn.guard?.tax_question && (
        <p className="mt-3 rounded-md bg-accent-soft px-3 py-2 text-sm text-accent">
          Tax is outside this guide&apos;s scope. For tax questions, ask a tax advisor (Steuerberater / CPA).
        </p>
      )}

      {turn.status === "streaming" && (
        <p className="mt-3 flex items-center gap-2 text-sm text-ink-soft" aria-live="polite">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
          {lastProgress?.label ?? "Starting"}…
        </p>
      )}

      {text && (
        <div className="answer mt-3">
          <ReactMarkdown remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children }) => {
                const match = href?.match(/^#cite-(\d+)$/);
                if (!match) return <a href={href} target="_blank" rel="noreferrer" className="text-accent underline">{children}</a>;
                const n = Number(match[1]);
                const bad = invalid.has(n);
                return (
                  <button type="button" onClick={(e) => { e.stopPropagation(); onSelect(); onCite(n); }}
                    title={bad ? "Not a retrieved source: this citation could not be verified" : `Show source ${n}`}
                    className={`mx-0.5 rounded px-1 text-xs font-semibold align-super ${bad ? "bg-danger-soft text-danger line-through" : "bg-accent-soft text-accent"}`}>
                    {n}
                  </button>
                );
              },
            }}>
            {linkCitations(text)}
          </ReactMarkdown>
        </div>
      )}

      {turn.answer && !turn.answer.citations.ok && (
        <p className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          Citation check: {turn.answer.citations.invalid.map((n) => `[${n}]`).join(", ")} do not match any
          retrieved source. Treat those statements with extra caution.
        </p>
      )}

      {turn.error && <p className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{turn.error}</p>}

      {turn.answer && (
        <p className="mt-4 border-t border-line pt-2 text-xs text-ink-soft">
          {turn.answer.usage.total_tokens > 0 &&
            `${turn.answer.usage.total_tokens.toLocaleString()} tokens (${turn.answer.usage.input_tokens.toLocaleString()} in / ${turn.answer.usage.output_tokens.toLocaleString()} out)` +
              (turn.answer.usage.cost_usd != null ? ` · ≈ $${turn.answer.usage.cost_usd.toFixed(3)}` : "") +
              " · "}
          {turn.answer.disclaimer}
        </p>
      )}
    </article>
  );
}
