"use client";

import type { SynthesisData } from "@/types";

function formatBias(dir?: string): string | null {
  switch ((dir || "").toUpperCase()) {
    case "BULLISH":
      return "Bullish";
    case "BEARISH":
      return "Bearish";
    case "NEUTRAL":
      return "Neutral";
    case "MIXED":
      return "Neutral";
    default:
      return null;
  }
}

function formatHorizon(horizon?: string): string | null {
  if (!horizon) return null;
  return horizon.replace(/_/g, " ");
}

function biasClass(bias: string) {
  if (bias === "Bullish") return "text-emerald-400";
  if (bias === "Bearish") return "text-red-400";
  return "text-[var(--text-secondary)]";
}

/** Compact one-line analysis meta — only for real market research responses. */
export function ResultCard({ synthesis }: { synthesis: SynthesisData | null }) {
  if (!synthesis) return null;

  const bias = formatBias(synthesis.overall_direction);
  const horizon = formatHorizon(synthesis.horizon);
  const confidence =
    typeof synthesis.confidence === "number" && Number.isFinite(synthesis.confidence)
      ? Math.round(Math.max(0, Math.min(1, synthesis.confidence)) * 100)
      : null;

  // Hide for incomplete / non-analysis payloads
  if (bias == null || horizon == null || confidence == null) return null;

  return (
    <div className="max-w-3xl mx-auto px-4 pb-2">
      <p className="text-xs text-[var(--text-secondary)] tracking-wide">
        <span className="text-[var(--text-secondary)]">Confidence</span>{" "}
        <span className="text-[var(--text)] font-medium tabular-nums">{confidence}%</span>
        <span className="mx-2 text-[#555]">·</span>
        <span className="text-[var(--text-secondary)]">Time Horizon</span>{" "}
        <span className="text-[var(--text)] font-medium capitalize">{horizon}</span>
        <span className="mx-2 text-[#555]">·</span>
        <span className="text-[var(--text-secondary)]">Market Bias</span>{" "}
        <span className={`font-medium ${biasClass(bias)}`}>{bias}</span>
      </p>
    </div>
  );
}
