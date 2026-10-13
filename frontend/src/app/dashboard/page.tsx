"use client";

import Link from "next/link";
import { useState, useSyncExternalStore } from "react";

import { fetchDashboard } from "@/lib/api";
import type { Dashboard } from "@/lib/types";

const TOKEN_KEY = "flg-admin-token";
const AREAS = [
  "data_protection", "ai_regulation", "platform_law", "company_formation", "contracts",
  "intellectual_property", "employment", "cybersecurity_product", "fundraising",
];
const JURISDICTIONS = ["EU", "DE", "US"];
const label = (s: string) => s.replaceAll("_", " ");

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function readSavedToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function Tile({ value, caption }: { value: string; caption: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <p className="font-serif text-3xl">{value}</p>
      <p className="mt-1 text-sm text-ink-soft">{caption}</p>
    </div>
  );
}

function CoverageGrid({ cells }: { cells: Dashboard["coverage"] }) {
  const find = (area: string, j: string) => cells.find((c) => c.legal_area === area && c.jurisdiction === j);
  return (
    <table className="w-full border-separate border-spacing-[2px] text-sm">
      <thead>
        <tr><th className="text-left font-normal text-ink-soft">Legal Area</th>{JURISDICTIONS.map((j) => <th key={j} className="font-normal text-ink-soft">{j}</th>)}</tr>
      </thead>
      <tbody>
        {AREAS.map((area) => (
          <tr key={area}>
            <td className="pr-2 capitalize">{label(area)}</td>
            {JURISDICTIONS.map((j) => {
              const c = find(area, j);
              if (!c) return <td key={j} className="rounded bg-paper text-center text-xs text-ink-soft">out of scope</td>;
              const share = c.required ? c.indexed / c.required : 0;
              return (
                <td key={j} title={c.missing.length ? `Missing: ${c.missing.join(", ")}` : "All required Sources indexed"}
                  className="rounded px-2 py-1.5 text-center text-xs font-medium"
                  style={{ background: `color-mix(in oklab, var(--accent) ${Math.round(15 + share * 55)}%, var(--surface))`, color: share > 0.6 ? "var(--surface)" : "var(--ink)" }}>
                  {c.indexed}/{c.required}{c.depth === "deep" ? " · deep" : ""}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RecallBars({ runs }: { runs: Record<string, string | number | null>[] }) {
  const rows = runs.filter((r) => typeof r.recall === "number").sort((a, b) => (b.recall as number) - (a.recall as number));
  if (!rows.length) return <p className="text-sm text-ink-soft">No retrieval evaluation yet.</p>;
  return (
    <div className="space-y-1.5" role="list">
      {rows.map((r) => {
        const recall = r.recall as number;
        return (
          <div key={String(r.strategy)} role="listitem" className="group flex items-center gap-2 text-sm"
            title={`${r.strategy}: recall ${recall.toFixed(2)}, hit rate ${Number(r.hit_rate).toFixed(2)}, MRR ${Number(r.mrr).toFixed(2)}`}>
            <span className="w-24 shrink-0 font-medium">{String(r.strategy)}</span>
            <span className="relative h-4 flex-1">
              <span className="absolute inset-y-0 left-0 rounded-r bg-accent group-hover:opacity-80" style={{ width: `${recall * 100}%` }} />
            </span>
            <span className="w-12 text-right tabular-nums text-ink-soft">{recall.toFixed(2)}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function DashboardPage() {
  // The saved token is read on the client only (the server renders without it).
  const saved = useSyncExternalStore(subscribe, readSavedToken, () => "");
  const [typed, setToken] = useState<string | null>(null);
  const token = typed ?? saved;
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setData(await fetchDashboard(token));
      try { sessionStorage.setItem(TOKEN_KEY, token); } catch {}
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const retrieval = data?.evaluations.find((e) => e.file.includes("retrieval"));
  const answers = data?.evaluations.filter((e) => e.file.includes("answers")) ?? [];

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <div className="flex items-baseline justify-between">
        <h1 className="font-serif text-3xl">Dashboard</h1>
        <Link href="/" className="text-sm text-accent underline">Back to the guide</Link>
      </div>
      <p className="rounded-md bg-warn-soft px-3 py-1.5 text-sm text-warn">
        This is general legal information, not legal advice. It does not replace consultation with a qualified lawyer.
      </p>

      {!data && (
        <form className="flex max-w-md gap-2" onSubmit={(e) => { e.preventDefault(); load(); }}>
          <label htmlFor="token" className="sr-only">Admin token</label>
          <input id="token" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Admin token"
            className="flex-1 rounded-md border border-line bg-surface px-2 py-1.5" />
          <button className="rounded-md bg-accent px-3 font-medium text-surface">Open</button>
        </form>
      )}
      {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}

      {data && (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Tile value={String(data.usage.requests)} caption="questions (last 500)" />
            <Tile value={`$${data.usage.cost_usd.toFixed(2)}`} caption="answer cost (estimate)" />
            <Tile value={String(data.usage.escalations)} caption="answers with Escalation Triggers" />
            <Tile value={String(data.usage.gap_signals)} caption="Gap Signals" />
            <Tile value={String(data.pending_reviews)} caption="changes waiting for review" />
          </section>

          <section className="grid gap-6 lg:grid-cols-2">
            <div className="rounded-lg border border-line bg-surface p-4">
              <h2 className="font-serif text-xl">Coverage Map</h2>
              <p className="mb-3 text-sm text-ink-soft">Required Sources indexed per cell (hover for what is missing).</p>
              <CoverageGrid cells={data.coverage} />
            </div>
            <div className="rounded-lg border border-line bg-surface p-4">
              <h2 className="font-serif text-xl">Retrieval recall by strategy</h2>
              <p className="mb-3 text-sm text-ink-soft">
                Share of expected passages retrieved, Golden Set{retrieval?.reviewed_only ? " (reviewed items)" : " (incl. drafts)"}.
              </p>
              <RecallBars runs={retrieval?.runs ?? []} />
              {retrieval && (
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer text-ink-soft">Table</summary>
                  <table className="mt-2 w-full text-left text-xs">
                    <thead><tr><th>Strategy</th><th>hit@k</th><th>recall</th><th>MRR</th></tr></thead>
                    <tbody>{retrieval.runs.map((r) => (
                      <tr key={String(r.strategy)} className="border-t border-line"><td>{String(r.strategy)}</td><td>{String(r.hit_rate)}</td><td>{String(r.recall)}</td><td>{String(r.mrr)}</td></tr>
                    ))}</tbody>
                  </table>
                </details>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-line bg-surface p-4">
            <h2 className="font-serif text-xl">Answer evaluations</h2>
            {answers.length === 0 ? <p className="text-sm text-ink-soft">No answer evaluation yet.</p> : (
              <table className="mt-2 w-full text-left text-sm">
                <thead className="text-ink-soft"><tr><th>Strategy</th><th>Mode</th><th>Model</th><th>Cited expected</th><th>Citations valid</th><th>Escalations</th><th>Median s</th></tr></thead>
                <tbody>{answers.flatMap((e) => e.runs).map((r, i) => (
                  <tr key={i} className="border-t border-line">
                    <td>{String(r.strategy)}</td><td>{String(r.mode)}</td><td>{String(r.model)}</td>
                    <td>{String(r.cited_expected)}</td><td>{String(r.citations_valid)}</td><td>{String(r.escalation_accuracy)}</td><td>{String(r.median_seconds)}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </section>

          <section className="grid gap-6 lg:grid-cols-2">
            <div className="rounded-lg border border-line bg-surface p-4">
              <h2 className="font-serif text-xl">Usage by model</h2>
              <table className="mt-2 w-full text-left text-sm">
                <thead className="text-ink-soft"><tr><th>Model</th><th>Questions</th><th>Tokens</th><th>Cost</th><th>Median s</th></tr></thead>
                <tbody>{Object.entries(data.usage.by_model).map(([model, m]) => (
                  <tr key={model} className="border-t border-line"><td>{model}</td><td>{m.requests}</td><td>{m.tokens.toLocaleString()}</td><td>${m.cost_usd.toFixed(3)}</td><td>{m.median_seconds}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <div className="rounded-lg border border-line bg-surface p-4">
              <h2 className="font-serif text-xl">Gap Signals</h2>
              <p className="text-sm text-ink-soft">Questions answered without citations, or from Tier 3 pages only: candidates for new Sources.</p>
              <ul className="mt-2 space-y-1 text-sm">
                {data.gap_signals.length === 0 && <li className="text-ink-soft">None yet.</li>}
                {data.gap_signals.map((g, i) => (
                  <li key={i} className="border-t border-line pt-1"><span className="font-medium">{label(g.signal)}</span> · {g.question}</li>
                ))}
              </ul>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
