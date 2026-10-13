const STATUS: Record<string, { label: string; className: string }> = {
  in_force: { label: "in force", className: "text-ok" },
  pending_proposal: { label: "proposal, not law", className: "text-warn" },
  repealed: { label: "repealed", className: "text-danger" },
};

export function SourceBadges({ tier, jurisdiction, status }: { tier: number; jurisdiction: string; status: string }) {
  const s = STATUS[status] ?? { label: status, className: "text-ink-soft" };
  return (
    <span className="flex flex-wrap gap-1.5 text-[11px] font-medium uppercase tracking-wide">
      <span className="rounded bg-accent-soft px-1.5 py-0.5 text-accent">Tier {tier}</span>
      <span className="rounded border border-line px-1.5 py-0.5 text-ink-soft">{jurisdiction}</span>
      <span className={`rounded border border-line px-1.5 py-0.5 ${s.className}`}>{s.label}</span>
    </span>
  );
}
