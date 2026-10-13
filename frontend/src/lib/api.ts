import type { ChangeRecord, ChatEvent, Dashboard, Options, Settings, Turn, UpdateEvent } from "./types";

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {}
  return `Request failed (${response.status})`;
}

export async function fetchOptions(): Promise<Options> {
  const response = await fetch("/api/options", { cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}

/** Streams one chat turn. Calls `onEvent` for every server-sent event. */
export async function streamChat(
  question: string,
  settings: Settings,
  history: Turn[],
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    signal,
    body: JSON.stringify({
      question,
      strategy: settings.strategy,
      answer_model: settings.answerModel,
      answering_mode: settings.answeringMode,
      jurisdictions: settings.jurisdictions.length ? settings.jurisdictions : null,
      profile: settings.profile,
      history: history
        .filter((t) => t.answer)
        .slice(-5)
        .flatMap((t) => [
          { role: "user", content: t.question },
          { role: "assistant", content: t.answer!.text },
        ]),
    }),
  });
  if (!response.ok || !response.body) throw new Error(await errorMessage(response));
  await readEvents(response, (data) => onEvent(data as ChatEvent));
}

/** Reads a server-sent event stream and passes each event's JSON data on. */
async function readEvents(response: Response, onData: (data: unknown) => void): Promise<void> {
  const reader = response.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) onData(JSON.parse(data));
    }
  }
}

export async function fetchChanges(): Promise<ChangeRecord[]> {
  const response = await fetch("/api/changes?limit=100", { cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()).changes;
}

const auth = (token: string) => ({ authorization: `Bearer ${token}` });

export async function checkAdmin(token: string): Promise<void> {
  const response = await fetch("/api/admin/check", { headers: auth(token), cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response));
}

export async function runUpdate(token: string, onEvent: (event: UpdateEvent) => void): Promise<void> {
  const response = await fetch("/api/admin/update", {
    method: "POST",
    headers: { ...auth(token), "content-type": "application/json" },
    body: "{}",
  });
  if (!response.ok || !response.body) throw new Error(await errorMessage(response));
  await readEvents(response, (data) => onEvent(data as UpdateEvent));
}

export async function decideChange(token: string, id: number, decision: "approve" | "reject"): Promise<void> {
  const response = await fetch(`/api/admin/changes/${id}/${decision}`, { method: "POST", headers: auth(token) });
  if (!response.ok) throw new Error(await errorMessage(response));
}

export async function fetchDashboard(token: string): Promise<Dashboard> {
  const response = await fetch("/api/admin/dashboard", { headers: auth(token), cache: "no-store" });
  if (!response.ok) throw new Error(await errorMessage(response));
  return response.json();
}
