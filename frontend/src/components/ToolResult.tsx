"use client";

import type { ToolEvent } from "@/lib/types";

const RISK: Record<string, { label: string; cls: string }> = {
  prohibited: { label: "Prohibited", cls: "bg-danger-soft text-danger" },
  high_risk: { label: "High-risk", cls: "bg-warn-soft text-warn" },
  transparency: { label: "Transparency duties", cls: "bg-accent-soft text-accent" },
  minimal: { label: "Minimal risk", cls: "bg-accent-soft text-ok" },
};
const APPLIES: Record<string, string> = { yes: "text-warn", no: "text-ok", unclear: "text-ink-soft" };
const CURRENCY: Record<string, string> = {
  up_to_date: "text-ok", newer_version_available: "text-warn", not_indexed: "text-ink-soft", unknown: "text-ink-soft", unsupported: "text-ink-soft",
};
const TITLES: Record<string, string> = {
  classify_ai_system: "AI Act risk classifier",
  check_applicability: "Applicability check",
  compliance_timeline: "Compliance timeline",
  check_source_currency: "Live source check",
};

/** Visualises one domain-tool call in the "how this answer was found" panel. */
export function ToolResult({ event }: { event: ToolEvent }) {
  const r = event.result;
  return (
    <section className="rounded-md border border-line p-3">
      <h3 className="text-xs uppercase tracking-wide text-ink-soft">Rule check · {TITLES[event.name] ?? event.name}</h3>
      {r?.error ? (
        <p className="mt-2 text-xs text-danger">{r.error}</p>
      ) : event.name === "classify_ai_system" ? (
        <div className="mt-2 space-y-2 text-xs">
          <p>
            <span className={`rounded px-1.5 py-0.5 font-semibold ${RISK[r.risk_class]?.cls}`}>{RISK[r.risk_class]?.label ?? r.risk_class}</span>
            <span className="ml-2 text-ink-soft">role: {r.role.replace("_", " ")}</span>
          </p>
          {r.reasons.map((x: string, i: number) => <p key={i} className="text-ink-soft">{x}</p>)}
          {r.obligations.length > 0 && (
            <table className="w-full border-collapse">
              <tbody>
                {r.obligations.map((o: { reference: string; duty: string; applies_from: string | null }, i: number) => (
                  <tr key={i} className="border-t border-line align-top">
                    <td className="py-1 pr-2 font-medium whitespace-nowrap">{o.reference}</td>
                    <td className="py-1 pr-2 text-ink-soft">{o.duty}</td>
                    <td className="py-1 whitespace-nowrap">{o.applies_from ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : event.name === "check_applicability" ? (
        <div className="mt-2 text-xs">
          <p className="text-ink-soft">Company size: {r.company_size}</p>
          <ul className="mt-1 space-y-1">
            {r.results.map((x: { law: string; applies: string; reasons: string[] }) => (
              <li key={x.law}>
                <span className="font-semibold">{x.law}</span>{" "}
                <span className={`font-semibold uppercase ${APPLIES[x.applies]}`}>{x.applies}</span>
                <span className="block text-ink-soft">{x.reasons[0]}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : event.name === "compliance_timeline" ? (
        <ol className="mt-2 space-y-1 text-xs">
          {r.events.map((e: { date: string; source: string; what: string; status: string }, i: number) => (
            <li key={i} className="flex gap-2">
              <span className={`w-20 shrink-0 font-medium ${e.status === "upcoming" ? "text-warn" : "text-ink-soft"}`}>{e.date}</span>
              <span><span className="font-semibold">{e.source}</span> <span className="text-ink-soft">{e.what}</span></span>
            </li>
          ))}
        </ol>
      ) : event.name === "check_source_currency" ? (
        <p className="mt-2 text-xs">
          <span className="font-semibold">{r.source_id}</span>{" "}
          <span className={`font-semibold ${CURRENCY[r.status]}`}>{r.status.replaceAll("_", " ")}</span>
          <span className="block text-ink-soft">{r.detail}</span>
        </p>
      ) : (
        <pre className="mt-2 overflow-x-auto text-xs">{JSON.stringify(r, null, 2)}</pre>
      )}
    </section>
  );
}
