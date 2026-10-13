"use client";

import { useEffect, useRef } from "react";

import type { Turn } from "@/lib/types";
import { SourceBadges } from "./Badges";
import { ToolResult } from "./ToolResult";

/** "How this answer was found": progress, rewritten queries, retrieved passages. */
export function TracePanel({ turn, focus }: { turn: Turn | undefined; focus: number | null }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focus == null) return;
    container.current?.querySelector(`#source-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focus, turn?.id]);

  if (!turn) {
    return <p className="text-sm text-ink-soft">Ask a question to see how the answer is found: which searches ran, and which passages were retrieved.</p>;
  }
  const cited = new Set(turn.answer?.citations.cited ?? []);

  return (
    <div ref={container} className="space-y-5 text-sm">
      <section>
        <h3 className="text-xs uppercase tracking-wide text-ink-soft">Steps</h3>
        <ol className="mt-2 space-y-1">
          {turn.progress.map((p, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-ok">✓</span>
              <span>{p.label}</span>
            </li>
          ))}
          {turn.answer && (
            <li className="flex gap-2">
              <span className={turn.answer.citations.ok ? "text-ok" : "text-danger"}>{turn.answer.citations.ok ? "✓" : "✗"}</span>
              <span>Citation check: {turn.answer.citations.cited.length} verified, {turn.answer.citations.invalid.length} unverified</span>
            </li>
          )}
        </ol>
      </section>

      {turn.guard && (
        <section className="rounded-md border border-line p-3 text-xs">
          <h3 className="uppercase tracking-wide text-ink-soft">Question check ({turn.guard.method})</h3>
          <p className="mt-1">
            Escalation triggers: {turn.guard.triggers.length ? turn.guard.triggers.map((t) => t.id).join(", ") : "none"} ·
            Personal data removed: {turn.guard.personal_data.length ? turn.guard.personal_data.join(", ") : "none"} ·
            Tax: {turn.guard.tax_question ? "yes" : "no"}
          </p>
        </section>
      )}

      {turn.tools.map((tool, i) => <ToolResult key={`tool-${i}`} event={tool} />)}

      {turn.searches.map((search, i) => (
        <section key={i} className="rounded-md border border-line p-3">
          <h3 className="text-xs uppercase tracking-wide text-ink-soft">
            Search {i + 1} · {search.strategy}
            {search.reranked && " · reranked"}
          </h3>
          <ul className="mt-2 space-y-1">
            {search.queries.map((q, j) => (
              <li key={j} className="flex gap-2">
                <span className="w-6 shrink-0 text-xs font-semibold uppercase text-ink-soft">{q.language ?? "?"}</span>
                <span className="italic">{q.text}</span>
              </li>
            ))}
          </ul>
          <ul className="mt-3 space-y-2">
            {search.hits.map((hit) => (
              <li key={hit.n} id={`source-${hit.n}`}
                className={`rounded-md border p-2 ${focus === hit.n ? "border-accent bg-accent-soft" : cited.has(hit.n) ? "border-line" : "border-line opacity-70"}`}>
                <div className="flex items-start justify-between gap-2">
                  <span className="font-semibold">[{hit.n}] {hit.label}</span>
                  <span className="shrink-0 text-xs text-ink-soft">{hit.score.toFixed(3)}</span>
                </div>
                <div className="mt-1 text-xs text-ink-soft">
                  {hit.url ? <a href={hit.url} target="_blank" rel="noreferrer" className="underline">{hit.source_title}</a> : hit.source_title}
                </div>
                <div className="mt-1"><SourceBadges tier={hit.tier} jurisdiction={hit.jurisdiction} status={hit.legal_status} /></div>
                <p className="mt-1.5 line-clamp-4 text-xs leading-relaxed text-ink-soft">{hit.excerpt}</p>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
