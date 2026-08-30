"use client";

import { useState } from "react";
import type { AgentConflictAnalysis } from "@/types";

const AGENTS = ["News", "Fundamental", "Technical"] as const;
const AGENT_KEYS = ["news", "fundamental", "technical"] as const;

function relationColor(relation: string) {
  switch (relation) {
    case "AGREEMENT":
      return "bg-emerald-950/60 text-emerald-400 border-emerald-800";
    case "PARTIAL_AGREEMENT":
      return "bg-sky-950/50 text-sky-300 border-sky-800";
    case "DIRECTION_CONFLICT":
      return "bg-red-950/50 text-red-400 border-red-800";
    case "HORIZON_CONFLICT":
      return "bg-[#3a3a3a] text-[#d4d4d4] border-[#555555]";
    case "DATA_CONFLICT":
      return "bg-orange-950/40 text-orange-300 border-orange-800";
    default:
      return "bg-[#2a2a2a] text-[var(--text-secondary)] border-[var(--border)]";
  }
}

function relationLabel(relation: string) {
  return relation.replace(/_/g, " ");
}

function findRelation(
  conflicts: AgentConflictAnalysis | null | undefined,
  a: string,
  b: string,
) {
  if (!conflicts?.relations) return null;
  return conflicts.relations.find(
    (r) =>
      (r.agent_a === a && r.agent_b === b) ||
      (r.agent_a === b && r.agent_b === a),
  );
}

export function AgentConflictMatrix({
  conflicts,
}: {
  conflicts: AgentConflictAnalysis | null | undefined;
}) {
  const [selected, setSelected] = useState<string | null>(null);

  if (!conflicts?.relations?.length) return null;

  return (
    <div className="space-y-2">
      <p className="text-xs uppercase tracking-wide text-[var(--text-secondary)] font-semibold">
        Agent Agreement / Contradiction
      </p>
      {conflicts.agreement_summary ? (
        <p className="text-sm text-[var(--text)]">{conflicts.agreement_summary}</p>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr>
              <th className="p-1.5 text-left text-[var(--text-secondary)]" />
              {AGENTS.map((a) => (
                <th key={a} className="p-1.5 text-center text-[var(--text-secondary)] font-medium">
                  {a}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {AGENT_KEYS.map((rowKey, ri) => (
              <tr key={rowKey}>
                <td className="p-1.5 font-medium text-[var(--text-secondary)]">{AGENTS[ri]}</td>
                {AGENT_KEYS.map((colKey, ci) => {
                  if (ri === ci) {
                    return (
                      <td key={colKey} className="p-1.5 text-center text-[var(--text-secondary)]">
                        —
                      </td>
                    );
                  }
                  if (ri > ci) {
                    return <td key={colKey} className="p-1.5" />;
                  }
                  const rel = findRelation(conflicts, rowKey, colKey);
                  if (!rel) {
                    return (
                      <td key={colKey} className="p-1.5 text-center text-[var(--text-secondary)]">
                        —
                      </td>
                    );
                  }
                  const cellKey = `${rowKey}-${colKey}`;
                  return (
                    <td key={colKey} className="p-1.5">
                      <button
                        type="button"
                        onClick={() =>
                          setSelected(selected === cellKey ? null : cellKey)
                        }
                        className={`w-full px-2 py-1 rounded border text-[10px] font-medium ${relationColor(rel.relation)}`}
                      >
                        {relationLabel(rel.relation)}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected ? (
        <p className="text-xs text-[var(--text-secondary)] bg-[#262626] border border-[var(--border)] rounded-lg p-2">
          {conflicts.relations.find((r) => {
            const parts = selected.split("-");
            return (
              (r.agent_a === parts[0] && r.agent_b === parts[1]) ||
              (r.agent_a === parts[1] && r.agent_b === parts[0])
            );
          })?.explanation}
        </p>
      ) : null}
      {conflicts.confidence_adjustment != null && conflicts.confidence_adjustment !== 0 ? (
        <p className="text-[10px] text-[var(--text-secondary)]">
          Confidence adjustment from agent alignment:{" "}
          {conflicts.confidence_adjustment > 0 ? "+" : ""}
          {(conflicts.confidence_adjustment * 100).toFixed(0)}%
        </p>
      ) : null}
    </div>
  );
}
