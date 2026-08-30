"use client";

import { BrandLogo } from "@/components/BrandLogo";

const RESEARCH_SUGGESTIONS = [
  "What is the current XAU/USD price?",
  "3-month gold outlook analysis",
  "Short-term technical analysis for gold",
  "How do Fed rates affect gold right now?",
];

const TRADER_SUGGESTIONS = [
  "Intraday bias and key levels for XAU/USD",
  "Give me a trade setup with entry, SL and TP",
  "Where is gold likely to invalidate this session?",
  "Short-term technical analysis for gold",
];

export function WelcomeScreen({
  onSuggestion,
  tradeMode = false,
}: {
  onSuggestion: (text: string) => void;
  tradeMode?: boolean;
}) {
  const suggestions = tradeMode ? TRADER_SUGGESTIONS : RESEARCH_SUGGESTIONS;

  return (
    <div className="flex flex-col items-center justify-center flex-1 px-4 py-12">
      <BrandLogo size="lg" className="mb-6" />
      <h2 className="text-2xl font-semibold text-[var(--text)] mb-2">
        {tradeMode ? "Trader desk" : "Gold Research Agent"}
      </h2>
      <p className="text-[var(--text-secondary)] text-center max-w-md mb-8 text-[15px]">
        {tradeMode
          ? "Live XAU/USD levels, bias, and structured setups — analysis only, not advice."
          : "Policy-driven multi-agent analysis for XAU/USD — news, fundamentals, and technicals."}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => onSuggestion(s)}
            className="text-left px-4 py-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] hover:bg-[#3a3a3a] text-sm text-[var(--text)] transition-colors"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
