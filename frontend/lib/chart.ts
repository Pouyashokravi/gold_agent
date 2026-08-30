import type { ChartInterval, OhlcBar, XauQuote } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export const INTERVAL_MAP: Record<ChartInterval, string> = {
  "5m": "5min",
  "15m": "15min",
  "1H": "1h",
  "4H": "4h",
  "1D": "1day",
};

export const CHART_INTERVALS: ChartInterval[] = ["5m", "15m", "1H", "4H", "1D"];

export async function fetchXauOhlc(
  interval: ChartInterval = "1H",
  outputsize = 120,
): Promise<OhlcBar[]> {
  const tdInterval = INTERVAL_MAP[interval];
  const res = await fetch(
    `${API_BASE}/api/market/xau/ohlc?interval=${encodeURIComponent(tdInterval)}&outputsize=${outputsize}`,
  );
  if (!res.ok) {
    throw new Error(`OHLC fetch failed (${res.status})`);
  }
  const data = await res.json();
  return (data.values ?? []) as OhlcBar[];
}

export async function fetchXauQuote(): Promise<XauQuote> {
  const res = await fetch(`${API_BASE}/api/market/xau/quote`);
  if (!res.ok) {
    throw new Error(`Quote fetch failed (${res.status})`);
  }
  return (await res.json()) as XauQuote;
}

export function toChartTime(datetime: string): number {
  return Math.floor(new Date(datetime).getTime() / 1000);
}
