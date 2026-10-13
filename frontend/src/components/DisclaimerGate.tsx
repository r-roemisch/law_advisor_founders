"use client";

import { useState, useSyncExternalStore } from "react";

const KEY = "flg-disclaimer-ack-v1";

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function readAcknowledged(): boolean {
  try {
    return localStorage.getItem(KEY) === "yes";
  } catch {
    return false;
  }
}

/** First-run screen: the Founder must acknowledge the disclaimer before asking (ADR 0002). */
export function DisclaimerGate({ disclaimer }: { disclaimer: string }) {
  // The server snapshot hides the gate; the client shows it until acknowledged.
  const stored = useSyncExternalStore(subscribe, readAcknowledged, () => true);
  const [acceptedNow, setAcceptedNow] = useState(false);

  if (stored || acceptedNow) return null;

  const accept = () => {
    try {
      localStorage.setItem(KEY, "yes");
    } catch {}
    setAcceptedNow(true);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="gate-title"
        className="max-w-lg rounded-lg border border-line bg-surface p-6 shadow-xl">
        <h2 id="gate-title" className="font-serif text-2xl">Before you start</h2>
        <p className="mt-3 text-ink-soft leading-relaxed">
          The Founder Legal Guide explains what EU, German and US law generally requires of tech
          and AI startups and the steps founders typically take. It does not assess your specific
          situation.
        </p>
        <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 font-medium text-warn">{disclaimer}</p>
        <p className="mt-3 text-sm text-ink-soft">
          Please don&apos;t enter personal data about employees, customers or other people.
        </p>
        <button onClick={accept}
          className="mt-5 w-full rounded-md bg-accent px-4 py-2.5 font-medium text-surface hover:opacity-90">
          I understand: this is not legal advice
        </button>
      </div>
    </div>
  );
}
