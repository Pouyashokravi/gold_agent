"use client";

import type { SynthesisData } from "@/types";

function biasStyle(bias?: string) {
  if (bias === "BULLISH") return "text-emerald-400 bg-emerald-950/50 border-emerald-800";
  if (bias === "BEARISH") return "text-red-400 bg-red-950/50 border-red-800";
  return "text-[var(--text-secondary)] bg-[#2a2a2a] border-[var(--border)]";
}

function Level({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-[#262626] border border-[var(--border)] px-2.5 py-2">
      <span className="text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">{label}</span>
      <p className="font-medium tabular-nums text-[var(--text)] text-sm">{value}</p>
    </div>
  );
}

export function TraderAnalysisPanel({ synthesis }: { synthesis: SynthesisData | null }) {
  if (!synthesis) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[#1a1a1a] p-3 text-sm">
        <p className="text-xs font-semibold text-[var(--text)] mb-1">Setup</p>
        <p className="text-xs text-[var(--text-secondary)]">
          Run an analysis to populate entry, stop, and targets.
        </p>
      </div>
    );
  }

  const setup = synthesis.trade_setup;
  const confidence = setup?.confidence ?? synthesis.confidence;
  const bias = setup?.bias ?? synthesis.overall_direction;

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[#1a1a1a] p-3 text-sm space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold tracking-wide text-[var(--text)]">Setup</span>
        {bias ? (
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${biasStyle(bias)}`}>
            {bias === "NO_TRADE" ? "WAIT / NO TRADE" : bias}
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Level
          label="Confidence"
          value={confidence != null ? `${(confidence * 100).toFixed(0)}%` : "—"}
        />
        <Level label="R / R" value={setup?.risk_reward != null ? String(setup.risk_reward) : "—"} />
        <Level
          label="Entry"
          value={
            setup?.entry_zone?.length === 2
              ? `${setup.entry_zone[0]} – ${setup.entry_zone[1]}`
              : "—"
          }
        />
        <Level label="Stop" value={setup?.stop_loss != null ? String(setup.stop_loss) : "—"} />
        <Level
          label="Take profit"
          value={setup?.take_profit?.length ? setup.take_profit.join(" / ") : "—"}
        />
        <Level label="Bias" value={synthesis.overall_direction ?? "—"} />
      </div>

      {setup?.invalidation ? (
        <p className="text-[11px] text-[var(--text-secondary)] leading-snug">{setup.invalidation}</p>
      ) : null}

      {synthesis.key_risks?.length ? (
        <p className="text-[11px] text-[var(--text-secondary)] leading-snug">
          <span className="uppercase tracking-wide text-[10px]">Risks · </span>
          {synthesis.key_risks.join(" · ")}
        </p>
      ) : null}

      <p className="text-[10px] text-[var(--text-secondary)] border-t border-[var(--border)] pt-2">
        Market analysis only — not financial advice.
      </p>
    </div>
  );
}
