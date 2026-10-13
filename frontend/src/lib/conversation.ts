import type { Turn } from "./types";

const KEY = "flg-conversation-v1";
const DISCLAIMER =
  "This is general legal information, not legal advice. It does not replace consultation with a qualified lawyer.";

/** Finished turns of the current conversation, kept in this browser only. */
export function loadConversation(): Turn[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Turn[]).filter((t) => t.status !== "streaming") : [];
  } catch {
    return [];
  }
}

export function saveConversation(turns: Turn[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(turns.filter((t) => t.status !== "streaming")));
  } catch {}
}

function sources(turn: Turn): { n: number; label: string; url: string | null; tier: number }[] {
  const cited = new Set(turn.answer?.citations.cited ?? []);
  return turn.searches.flatMap((s) => s.hits).filter((h) => cited.has(h.n))
    .map((h) => ({ n: h.n, label: h.label, url: h.url, tier: h.tier }));
}

export function toMarkdown(turns: Turn[]): string {
  const parts = [`# Founder Legal Guide – conversation\n\n> ${DISCLAIMER}\n\nExported ${new Date().toISOString()}\n`];
  for (const t of turns) {
    parts.push(`## ${t.question}\n`);
    parts.push(`_${t.settings.answeringMode} · ${t.settings.strategy} · ${t.settings.answerModel}_\n`);
    if (t.guard?.triggers.length) parts.push(`**Talk to a lawyer:** ${t.guard.triggers.map((x) => x.label).join("; ")}\n`);
    parts.push(t.answer?.text ?? t.error ?? "");
    const cited = sources(t);
    if (cited.length) parts.push("\n**Sources**\n\n" + cited.map((s) => `- [${s.n}] ${s.label} (Tier ${s.tier})${s.url ? ` – ${s.url}` : ""}`).join("\n"));
    parts.push("\n---\n");
  }
  return parts.join("\n");
}

export function toCsv(turns: Turn[]): string {
  const quote = (v: unknown) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const header = ["question", "answer", "answering_mode", "strategy", "answer_model", "citations", "escalations", "tokens", "cost_usd", "disclaimer"];
  const rows = turns.map((t) => [
    t.question, t.answer?.text ?? t.error, t.settings.answeringMode, t.settings.strategy, t.settings.answerModel,
    sources(t).map((s) => `[${s.n}] ${s.label}`).join(" | "),
    (t.guard?.triggers ?? []).map((x) => x.id).join(" "), t.answer?.usage.total_tokens, t.answer?.usage.cost_usd, DISCLAIMER,
  ].map(quote).join(","));
  return [header.join(","), ...rows].join("\n");
}

export function toJson(turns: Turn[]): string {
  return JSON.stringify({ disclaimer: DISCLAIMER, exported_at: new Date().toISOString(), turns }, null, 2);
}

export function download(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
