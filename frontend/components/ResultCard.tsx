"use client";

import { AgentConflictMatrix } from "@/components/AgentConflictMatrix";
import type { SynthesisData } from "@/types";

function directionColor(dir?: string) {
  if (dir === "BULLISH") return "text-emerald-400 bg-emerald-950/50 border-emerald-800";
  if (dir === "BEARISH") return "text-red-400 bg-red-950/50 border-red-800";
  return "text-[var(--text-secondary)] bg-[#2a2a2a] border-[var(--border)]";
}

export function ResultCard({ synthesis }: { synthesis: SynthesisData | null }) {
  if (!synthesis) return null;

  return (
    <div className="max-w-3xl mx-auto px-4 pb-3">
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-sm space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-[var(--text)]">XAU/USD Analysis</span>
          <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${directionColor(synthesis.overall_direction)}`}>
            {synthesis.overall_direction}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3 text-[var(--text-secondary)]">
          <div>
            <span className="text-xs uppercase tracking-wide">Confidence</span>
            <p className="text-[var(--text)] font-medium">{((synthesis.confidence ?? 0) * 100).toFixed(0)}%</p>
          </div>
          <div>
            <span className="text-xs uppercase tracking-wide">Horizon</span>
            <p className="text-[var(--text)] font-medium capitalize">{synthesis.horizon?.replace("_", " ")}</p>
          </div>
        </div>
        {synthesis.key_drivers?.length ? (
          <div>
            <p className="text-xs uppercase tracking-wide text-[var(--text-secondary)] mb-1">Key drivers</p>
            <p className="text-[var(--text)]">{synthesis.key_drivers.join(" · ")}</p>
          </div>
        ) : null}
        <AgentConflictMatrix conflicts={synthesis.agent_conflicts} />
        {synthesis.contradictions?.length ? (
          <div>
            <p className="text-xs uppercase tracking-wide text-[var(--text-secondary)] mb-1">Contradictions</p>
            <ul className="text-sm text-[var(--text)] list-disc pl-4 space-y-0.5">
              {synthesis.contradictions.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {synthesis.trade_setup ? (
          <div className="rounded-lg border border-[var(--border)] bg-[#262626] p-3 space-y-2">
            <p className="text-xs uppercase tracking-wide text-[var(--text-secondary)] font-semibold">Trade Setup</p>
            <div className="grid grid-cols-2 gap-2 text-[var(--text)]">
              <div>
                <span className="text-xs text-[var(--text-secondary)]">Bias</span>
                <p className="font-medium">{synthesis.trade_setup.bias}</p>
              </div>
              <div>
                <span className="text-xs text-[var(--text-secondary)]">Entry Zone</span>
                <p className="font-medium tabular-nums">
                  {synthesis.trade_setup.entry_zone?.length === 2
                    ? `${synthesis.trade_setup.entry_zone[0]} – ${synthesis.trade_setup.entry_zone[1]}`
                    : "—"}
                </p>
              </div>
              <div>
                <span className="text-xs text-[var(--text-secondary)]">Stop Loss</span>
                <p className="font-medium tabular-nums">{synthesis.trade_setup.stop_loss ?? "—"}</p>
              </div>
              <div>
                <span className="text-xs text-[var(--text-secondary)]">Take Profit</span>
                <p className="font-medium tabular-nums">{synthesis.trade_setup.take_profit?.join(" / ") || "—"}</p>
              </div>
            </div>
            {synthesis.trade_setup.invalidation ? (
              <p className="text-xs text-[var(--text-secondary)]">{synthesis.trade_setup.invalidation}</p>
            ) : null}
          </div>
        ) : null}
        <div className="flex gap-2 flex-wrap">
          {synthesis.base_case && (
            <ScenarioPill label="Base" direction={synthesis.base_case.direction} weight={synthesis.base_case.weight} />
          )}
          {synthesis.bull_case && (
            <ScenarioPill label="Bull" direction={synthesis.bull_case.direction} weight={synthesis.bull_case.weight} />
          )}
          {synthesis.bear_case && (
            <ScenarioPill label="Bear" direction={synthesis.bear_case.direction} weight={synthesis.bear_case.weight} />
          )}
        </div>
      </div>
    </div>
  );
}

function ScenarioPill({ label, direction, weight }: { label: string; direction: string; weight: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#262626] border border-[var(--border)] text-xs">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="font-medium text-[var(--text)]">{direction}</span>
      <span className="text-[var(--text-secondary)]">{(weight * 100).toFixed(0)}%</span>
    </span>
  );
}
