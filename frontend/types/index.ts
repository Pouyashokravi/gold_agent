export type StreamEvent = {
  type: string;
  agent?: string;
  message?: string;
  data?: Record<string, unknown>;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type TradeSetupData = {
  bias?: string;
  entry_zone?: number[];
  stop_loss?: number | null;
  take_profit?: number[];
  risk_reward?: number | null;
  invalidation?: string;
  invalidation_level?: number | null;
  confidence?: number;
};

export type ChartLevelsData = {
  trend?: string;
  support_levels?: number[];
  resistance_levels?: number[];
  invalidation_level?: number | null;
};

export type ChartAnnotationsData = {
  levels?: ChartLevelsData | null;
  trade_setup?: TradeSetupData | null;
  default_interval?: string;
};

export type AgentPairRelation = {
  agent_a: string;
  agent_b: string;
  relation: string;
  severity: number;
  explanation: string;
};

export type AgentConflictAnalysis = {
  relations?: AgentPairRelation[];
  agreement_summary?: string;
  confidence_adjustment?: number;
  dominant_conflict?: string | null;
};

export type SynthesisData = {
  overall_direction?: string;
  confidence?: number;
  horizon?: string;
  key_drivers?: string[];
  key_risks?: string[];
  trade_setup?: TradeSetupData | null;
  chart_annotations?: ChartAnnotationsData | null;
  agent_conflicts?: AgentConflictAnalysis | null;
  agreements?: string[];
  contradictions?: string[];
  base_case?: { direction: string; weight: number };
  bull_case?: { direction: string; weight: number };
  bear_case?: { direction: string; weight: number };
};

export type OhlcBar = {
  datetime: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

export type ChartInterval = "5m" | "15m" | "1H" | "4H" | "1D";

export type XauQuote = {
  symbol: string;
  close: number | null;
  open?: number | null;
  high: number | null;
  low: number | null;
  previous_close?: number | null;
  change: number | null;
  percent_change: number | null;
  datetime?: string;
  error?: string;
};
