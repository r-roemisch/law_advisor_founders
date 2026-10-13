"use client";

import { useState } from "react";

import type { FounderProfile, Jurisdiction } from "@/lib/types";

export const EMPTY_PROFILE: FounderProfile = {
  stage: "idea",
  company_seat: "none",
  target_markets: [],
  ai_involvement: "none",
  customers: "b2b",
  children_possible: false,
  headcount: "1-9",
  revenue: "<2m",
};

const AI_ROLE: Record<FounderProfile["ai_involvement"], string> = {
  none: "no AI Act role",
  internal_tools: "deployer",
  product_on_third_party_model: "provider",
  trains_or_finetunes: "provider",
  offers_gpai_model: "GPAI model provider",
};

export function profileSummary(p: FounderProfile): string {
  const seat = { DE: "German company", other_eu: "EU company", none: "no company yet" }[p.company_seat];
  const markets = p.target_markets.length ? `selling to ${p.target_markets.join(", ")}` : "markets not set";
  return `${seat} · ${markets} · AI: ${AI_ROLE[p.ai_involvement]}`;
}

type Option<T> = { value: T; label: string };

function Choice<T extends string>(props: { legend: string; hint?: string; value: T; options: Option<T>[]; onChange: (v: T) => void }) {
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-sm font-medium">{props.legend}</legend>
      {props.hint && <p className="text-xs text-ink-soft">{props.hint}</p>}
      <div className="flex flex-wrap gap-1.5">
        {props.options.map((o) => (
          <button key={o.value} type="button" aria-pressed={props.value === o.value} onClick={() => props.onChange(o.value)}
            className={`rounded-md border px-2.5 py-1 text-sm ${props.value === o.value ? "border-accent bg-accent-soft text-accent" : "border-line"}`}>
            {o.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

/** The Founder Profile questionnaire: plain-language questions; the AI Act role is derived. */
export function ProfileDialog(props: { profile: FounderProfile | null; onSave: (p: FounderProfile | null) => void; onClose: () => void }) {
  const [p, setP] = useState<FounderProfile>(props.profile ?? EMPTY_PROFILE);
  const set = (patch: Partial<FounderProfile>) => setP({ ...p, ...patch });
  const toggleMarket = (m: Jurisdiction) =>
    set({ target_markets: p.target_markets.includes(m) ? p.target_markets.filter((x) => x !== m) : [...p.target_markets, m] });

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4" onClick={props.onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="profile-title" onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-xl">
        <h2 id="profile-title" className="font-serif text-2xl">Founder Profile</h2>
        <p className="mt-1 text-sm text-ink-soft">
          It decides which law is relevant to you. It never turns an answer into advice on your specific case,
          and it stays in this browser.
        </p>

        <div className="mt-5 space-y-4">
          <Choice legend="Where are you?" value={p.stage} onChange={(stage) => set({ stage })} options={[
            { value: "idea", label: "Idea" },
            { value: "pre_incorporation", label: "About to incorporate" },
            { value: "incorporated_pre_revenue", label: "Incorporated, no revenue" },
            { value: "revenue_or_seed", label: "Revenue or seed funding" },
          ]} />
          <Choice legend="Where is (or will be) your company's seat?" value={p.company_seat} onChange={(company_seat) => set({ company_seat })} options={[
            { value: "DE", label: "Germany" },
            { value: "other_eu", label: "Another EU country" },
            { value: "none", label: "Not decided" },
          ]} />
          <fieldset className="space-y-1.5">
            <legend className="text-sm font-medium">Where do you sell?</legend>
            <div className="flex gap-1.5">
              {(["EU", "DE", "US"] as Jurisdiction[]).map((m) => (
                <button key={m} type="button" aria-pressed={p.target_markets.includes(m)} onClick={() => toggleMarket(m)}
                  className={`rounded-md border px-2.5 py-1 text-sm ${p.target_markets.includes(m) ? "border-accent bg-accent-soft text-accent" : "border-line"}`}>
                  {{ EU: "EU", DE: "Germany", US: "US" }[m]}
                </button>
              ))}
            </div>
          </fieldset>
          <Choice legend="How are you involved with AI?" hint={`Your AI Act role: ${AI_ROLE[p.ai_involvement]}`}
            value={p.ai_involvement} onChange={(ai_involvement) => set({ ai_involvement })} options={[
              { value: "none", label: "Not at all" },
              { value: "internal_tools", label: "We use AI tools internally" },
              { value: "product_on_third_party_model", label: "Our product is built on someone else's model" },
              { value: "trains_or_finetunes", label: "We train or fine-tune models" },
              { value: "offers_gpai_model", label: "We offer a general-purpose model" },
            ]} />
          <Choice legend="Who are your customers?" value={p.customers} onChange={(customers) => set({ customers })} options={[
            { value: "b2b", label: "Businesses" },
            { value: "b2c", label: "Consumers" },
            { value: "both", label: "Both" },
          ]} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={p.children_possible} onChange={(e) => set({ children_possible: e.target.checked })} />
            Children could use our product
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <Choice legend="Team size" value={p.headcount} onChange={(headcount) => set({ headcount })} options={[
              { value: "1-9", label: "1–9" }, { value: "10-49", label: "10–49" }, { value: "50-249", label: "50–249" }, { value: "250+", label: "250+" },
            ]} />
            <Choice legend="Annual revenue (EUR)" value={p.revenue} onChange={(revenue) => set({ revenue })} options={[
              { value: "<2m", label: "< 2M" }, { value: "2-10m", label: "2–10M" }, { value: "10-50m", label: "10–50M" }, { value: ">50m", label: "> 50M" },
            ]} />
          </div>
        </div>

        <div className="mt-6 flex justify-between gap-2">
          <button type="button" onClick={() => { props.onSave(null); props.onClose(); }} className="text-sm text-ink-soft underline">
            Clear profile
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={props.onClose} className="rounded-md border border-line px-4 py-2 text-sm">Cancel</button>
            <button type="button" onClick={() => { props.onSave(p); props.onClose(); }}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface">Save profile</button>
          </div>
        </div>
      </div>
    </div>
  );
}
