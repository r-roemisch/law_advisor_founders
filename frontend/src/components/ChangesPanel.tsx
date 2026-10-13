"use client";

import { useCallback, useEffect, useState } from "react";

import { checkAdmin, decideChange, fetchChanges, runUpdate } from "@/lib/api";
import type { ChangeRecord, UpdateEvent } from "@/lib/types";

const TOKEN_KEY = "flg-admin-token";

const STATUS: Record<ChangeRecord["status"], { label: string; cls: string }> = {
  applied: { label: "applied", cls: "bg-accent-soft text-ok" },
  review_needed: { label: "review needed", cls: "bg-warn-soft text-warn" },
  approved: { label: "approved", cls: "bg-accent-soft text-ok" },
  rejected: { label: "rejected", cls: "bg-danger-soft text-danger" },
};

function readToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

function sectionSummary(summary: ChangeRecord["summary"], kind: ChangeRecord["kind"]): string {
  const n = summary.added.length;
  if (kind === "added") return `${n} section${n === 1 ? "" : "s"} added to the Corpus`;
  const parts = [
    summary.modified.length && `${summary.modified.length} modified (${summary.modified.slice(0, 3).join(", ")}${summary.modified.length > 3 ? ", …" : ""})`,
    summary.added.length && `${summary.added.length} added (${summary.added.slice(0, 3).join(", ")}${summary.added.length > 3 ? ", …" : ""})`,
    summary.removed.length && `${summary.removed.length} removed`,
  ].filter(Boolean);
  return parts.join(" · ");
}

/** "What changed": the Change Records feed, plus admin-only update runs and review decisions. */
export function ChangesPanel({ onClose }: { onClose: () => void }) {
  const [changes, setChanges] = useState<ChangeRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState(readToken);
  const [admin, setAdmin] = useState(false);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);

  const load = useCallback(() => {
    fetchChanges().then(setChanges).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const unlock = async () => {
    try {
      await checkAdmin(token);
      try {
        sessionStorage.setItem(TOKEN_KEY, token);
      } catch {}
      setAdmin(true);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const update = async () => {
    setRunning(true);
    setLog([]);
    const append = (line: string) => setLog((l) => [...l, line]);
    try {
      await runUpdate(token, (event: UpdateEvent) => {
        if (event.type === "progress") append(`(${event.position}/${event.total}) ${event.source_id}`);
        else if (event.type === "change") append(`→ ${event.source_id} [${event.language}]: ${event.status.replace("_", " ")}`);
        else if (event.type === "failed") append(`✗ ${event.source_id}: ${event.error}`);
        else if (event.type === "summary")
          append(`Done: ${event.applied} applied, ${event.review_needed} for review, ${event.unchanged} unchanged, ${event.failed.length} failed.`);
        else if (event.type === "error") append(`Error: ${event.message}`);
      });
    } catch (e) {
      append(`Error: ${(e as Error).message}`);
    } finally {
      setRunning(false);
      load();
    }
  };

  const decide = async (id: number, decision: "approve" | "reject") => {
    try {
      await decideChange(token, id, decision);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside role="dialog" aria-modal="true" aria-labelledby="changes-title" onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-line bg-surface p-5 shadow-xl">
        <div className="flex items-baseline justify-between">
          <h2 id="changes-title" className="font-serif text-2xl">What changed</h2>
          <button onClick={onClose} className="text-sm text-ink-soft underline">Close</button>
        </div>
        <p className="mt-1 text-sm text-ink-soft">
          Every update to the Corpus: official texts are applied automatically; changed web pages wait for review.
        </p>

        <section className="mt-4 rounded-md border border-line p-3 text-sm">
          {admin ? (
            <div className="space-y-2">
              <button onClick={update} disabled={running}
                className="rounded-md bg-accent px-3 py-1.5 font-medium text-surface disabled:opacity-50">
                {running ? "Updating…" : "Run update now"}
              </button>
              {log.length > 0 && (
                <ol aria-live="polite" className="max-h-48 overflow-y-auto rounded bg-paper p-2 font-mono text-xs">
                  {log.map((line, i) => <li key={i}>{line}</li>)}
                </ol>
              )}
            </div>
          ) : (
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); unlock(); }}>
              <label htmlFor="admin-token" className="sr-only">Admin token</label>
              <input id="admin-token" type="password" value={token} onChange={(e) => setToken(e.target.value)}
                placeholder="Admin token (to run updates and review)" className="flex-1 rounded-md border border-line bg-paper px-2 py-1.5" />
              <button type="submit" className="rounded-md border border-line px-3">Unlock</button>
            </form>
          )}
        </section>

        {error && <p className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}

        <ol className="mt-4 space-y-2">
          {changes?.length === 0 && <li className="text-sm text-ink-soft">No changes recorded yet.</li>}
          {changes?.map((c) => (
            <li key={c.id} className="rounded-md border border-line p-3 text-sm">
              <div className="flex items-start justify-between gap-2">
                <span className="font-semibold">
                  {c.url ? <a href={c.url} target="_blank" rel="noreferrer" className="underline">{c.source}</a> : c.source}
                  <span className="ml-1 text-xs font-normal text-ink-soft">{c.jurisdiction} · {c.language}</span>
                </span>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${STATUS[c.status].cls}`}>{STATUS[c.status].label}</span>
              </div>
              <p className="mt-1 text-xs text-ink-soft">
                {new Date(c.detected_at).toLocaleString()} · {c.kind === "added" ? "added" : `${c.old_version} → ${c.new_version}`}
              </p>
              <p className="mt-1 text-xs">{sectionSummary(c.summary, c.kind)}</p>
              {admin && c.status === "review_needed" && (
                <div className="mt-2 flex gap-2">
                  <button onClick={() => decide(c.id, "approve")} className="rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-surface">Approve</button>
                  <button onClick={() => decide(c.id, "reject")} className="rounded-md border border-line px-2.5 py-1 text-xs">Reject</button>
                </div>
              )}
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
