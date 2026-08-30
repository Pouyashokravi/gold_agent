"use client";

const STEPS = [
  { id: "understanding", label: "Understanding", agentKey: null },
  { id: "planning", label: "Planning", agentKey: null },
  { id: "news_agent", label: "News", agentKey: "news" },
  { id: "fundamental_agent", label: "Fundamental", agentKey: "fundamental" },
  { id: "technical_agent", label: "Technical", agentKey: "technical" },
  { id: "synthesis", label: "Synthesis", agentKey: null },
  { id: "answer", label: "Answer", agentKey: null },
] as const;

type Props = {
  activeStep: string;
  completed: Set<string>;
  visible: boolean;
  statusMessage?: string;
  enabledAgents?: Record<string, boolean>;
};

export function AgentStatus({ activeStep, completed, visible, statusMessage, enabledAgents }: Props) {
  if (!visible) return null;

  return (
    <div className="max-w-3xl mx-auto px-4 pb-2">
      {statusMessage && (
        <p className="text-xs text-[var(--text-secondary)] mb-2 text-center">{statusMessage}</p>
      )}
      <div className="flex flex-wrap gap-2">
        {STEPS.map((step) => {
          const done = completed.has(step.id);
          const running = activeStep === step.id && !done;
          const skipped = step.agentKey && enabledAgents && enabledAgents[step.agentKey] === false;

          return (
            <span
              key={step.id}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all border ${
                skipped
                  ? "bg-[#2a2a2a] text-[#6a6a6a] border-[#3a3a3a] line-through"
                  : done
                    ? "bg-emerald-950/60 text-emerald-400 border-emerald-800"
                    : running
                      ? "bg-[#3a3a3a] text-[var(--text)] border-[#666666]"
                      : "bg-[#2a2a2a] text-[#6a6a6a] border-[#333333]"
              }`}
            >
              {running && !skipped && (
                <span className="flex gap-0.5">
                  <span className="typing-dot w-1 h-1 rounded-full bg-[#ececec] inline-block" />
                  <span className="typing-dot w-1 h-1 rounded-full bg-[#ececec] inline-block" />
                  <span className="typing-dot w-1 h-1 rounded-full bg-[#ececec] inline-block" />
                </span>
              )}
              {done && !skipped && (
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="3">
                  <path d="M5 13l4 4L19 7" />
                </svg>
              )}
              {step.label}
              {skipped ? " (skip)" : ""}
            </span>
          );
        })}
      </div>
    </div>
  );
}
