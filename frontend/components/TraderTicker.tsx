"use client";

import { fetchXauQuote } from "@/lib/chart";
import type { XauQuote } from "@/types";
import { useEffect, useState } from "react";

function fmt(n: number | null | undefined, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function TraderTicker() {
  const [quote, setQuote] = useState<XauQuote | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const data = await fetchXauQuote();
        if (cancelled) return;
        if (data.error && data.close == null) {
          setError(data.error);
          return;
        }
        setError(null);
        setQuote(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Quote unavailable");
      }
    };

    load();
    const id = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const change = quote?.change ?? null;
  const pct = quote?.percent_change ?? null;
  const positive = (change ?? pct ?? 0) >= 0;
  const changeColor =
    change == null && pct == null
      ? "text-[var(--text-secondary)]"
      : positive
        ? "text-[var(--up)]"
        : "text-[var(--down)]";

  return (
    <div className="px-4 py-3 border-b border-[var(--border)] bg-[#1a1a1a] shrink-0">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold tracking-wide text-[var(--text)]">XAU/USD</span>
            <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-[var(--text-secondary)]">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Live
            </span>
          </div>
          <p className="text-2xl font-semibold tabular-nums text-[var(--text)] leading-tight mt-0.5">
            {error && !quote ? "—" : fmt(quote?.close)}
          </p>
          <p className={`text-xs tabular-nums mt-0.5 ${changeColor}`}>
            {change != null ? `${positive ? "+" : ""}${fmt(change)}` : "—"}
            {pct != null ? `  (${positive ? "+" : ""}${fmt(pct, Math.abs(pct) < 0.01 ? 4 : 2)}%)` : ""}
          </p>
        </div>
        <div className="text-right text-[11px] text-[var(--text-secondary)] tabular-nums space-y-0.5 pt-0.5">
          <p>
            H <span className="text-[var(--text)]">{fmt(quote?.high)}</span>
          </p>
          <p>
            L <span className="text-[var(--text)]">{fmt(quote?.low)}</span>
          </p>
        </div>
      </div>
      {error ? (
        <p className="text-[10px] text-red-400 mt-1.5 truncate">{error}</p>
      ) : null}
    </div>
  );
}
