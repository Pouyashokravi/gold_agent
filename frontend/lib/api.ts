import type { StreamEvent } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export async function createConversation(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/conversations`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`Backend unreachable (${res.status}). Start uvicorn on :8000`);
  }
  const data = await res.json();
  return data.conversation_id;
}

export async function analyzeStream(
  query: string,
  conversationId: string,
  tradeMode: boolean,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ query, conversation_id: conversationId, trade_mode: tradeMode }),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Analyze failed (${res.status}): ${text || "backend error"}`);
  }
  if (!res.body) throw new Error("No response body from backend");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      for (const line of part.split("\n")) {
        const trimmed = line.trim();
        if (trimmed.startsWith("data: ")) {
          onEvent(JSON.parse(trimmed.slice(6)) as StreamEvent);
        }
      }
    }
  }
}
