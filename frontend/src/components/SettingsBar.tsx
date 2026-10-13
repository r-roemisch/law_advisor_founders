"use client";

import type { Jurisdiction, Options, Settings } from "@/lib/types";

import { profileSummary } from "./ProfileDialog";

const JURISDICTIONS: { id: Jurisdiction; label: string }[] = [
  { id: "EU", label: "EU" },
  { id: "DE", label: "Germany" },
  { id: "US", label: "US" },
];

type Props = {
  options: Options;
  settings: Settings;
  onChange: (s: Settings) => void;
  onEditProfile: () => void;
  disabled: boolean;
};

export function SettingsBar({ options, settings, onChange, onEditProfile, disabled }: Props) {
  const set = (patch: Partial<Settings>) => onChange({ ...settings, ...patch });
  const toggle = (j: Jurisdiction) =>
    set({
      jurisdictions: settings.jurisdictions.includes(j)
        ? settings.jurisdictions.filter((x) => x !== j)
        : [...settings.jurisdictions, j],
    });

  return (
    <fieldset disabled={disabled} className="flex flex-wrap items-end gap-x-4 gap-y-2 text-sm">
      <div className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wide text-ink-soft">Founder Profile</span>
        <button type="button" onClick={onEditProfile}
          className="max-w-[18rem] truncate rounded-md border border-line bg-surface px-2 py-1.5 text-left">
          {settings.profile ? profileSummary(settings.profile) : "Not set: add one"}
        </button>
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wide text-ink-soft">Answer model</span>
        <select value={settings.answerModel} onChange={(e) => set({ answerModel: e.target.value })}
          className="rounded-md border border-line bg-surface px-2 py-1.5">
          {options.answer_models.map((m) => (
            <option key={m.id} value={m.id}>{m.label ?? m.id}</option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wide text-ink-soft">Retrieval strategy</span>
        <select value={settings.strategy} onChange={(e) => set({ strategy: e.target.value })}
          className="max-w-[16rem] rounded-md border border-line bg-surface px-2 py-1.5">
          {options.strategies.map((s) => (
            <option key={s.name} value={s.name} title={s.description}>
              {s.name}: {s.description}
            </option>
          ))}
        </select>
      </label>

      <div className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wide text-ink-soft">Answering mode</span>
        <div className="flex overflow-hidden rounded-md border border-line" role="radiogroup">
          {options.answering_modes.map((m) => (
            <button key={m.name} type="button" role="radio" title={m.description}
              aria-checked={settings.answeringMode === m.name}
              onClick={() => set({ answeringMode: m.name })}
              className={`px-3 py-1.5 ${settings.answeringMode === m.name ? "bg-accent text-surface" : "bg-surface"}`}>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wide text-ink-soft">Jurisdictions</span>
        <div className="flex gap-1">
          {JURISDICTIONS.map((j) => {
            const on = settings.jurisdictions.includes(j.id);
            return (
              <button key={j.id} type="button" aria-pressed={on} onClick={() => toggle(j.id)}
                className={`rounded-full border px-3 py-1 ${on ? "border-accent bg-accent-soft text-accent" : "border-line bg-surface text-ink-soft"}`}>
                {j.label}
              </button>
            );
          })}
        </div>
      </div>
    </fieldset>
  );
}
