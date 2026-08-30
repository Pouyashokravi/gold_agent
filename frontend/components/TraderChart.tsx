"use client";

import type { ChartAnnotationsData, ChartInterval, OhlcBar } from "@/types";
import { CHART_INTERVALS, fetchXauOhlc, toChartTime } from "@/lib/chart";
import { useCallback, useEffect, useRef, useState } from "react";
import { createChart, type IChartApi, type ISeriesApi } from "lightweight-charts";

type TraderChartProps = {
  annotations?: ChartAnnotationsData | null;
  defaultInterval?: ChartInterval;
};

export function TraderChart({ annotations, defaultInterval = "1H" }: TraderChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const priceLinesRef = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]);
  const [interval, setInterval] = useState<ChartInterval>(defaultInterval);
  const [bars, setBars] = useState<OhlcBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async (iv: ChartInterval) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchXauOhlc(iv);
      setBars([...data].reverse());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load chart data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(interval);
  }, [interval, loadData]);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "#212121" },
        textColor: "#9b9b9b",
      },
      grid: {
        vertLines: { color: "#2f2f2f" },
        horzLines: { color: "#2f2f2f" },
      },
      width: containerRef.current.clientWidth,
      height: Math.max(containerRef.current.clientHeight, 180),
      timeScale: { borderColor: "#444444" },
      rightPriceScale: { borderColor: "#444444" },
      crosshair: {
        vertLine: { color: "#666666" },
        horzLine: { color: "#666666" },
      },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: Math.max(containerRef.current.clientHeight, 180),
        });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart || !bars.length) return;

    series.setData(
      bars.map((b) => ({
        time: toChartTime(b.datetime) as never,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      })),
    );

    priceLinesRef.current.forEach((pl) => series.removePriceLine(pl));
    priceLinesRef.current = [];

    const levels = annotations?.levels;
    const setup = annotations?.trade_setup;

    levels?.support_levels?.forEach((price) => {
      priceLinesRef.current.push(
        series.createPriceLine({
          price,
          color: "#10b981",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "Support",
        }),
      );
    });

    levels?.resistance_levels?.forEach((price) => {
      priceLinesRef.current.push(
        series.createPriceLine({
          price,
          color: "#ef4444",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "Resistance",
        }),
      );
    });

    if (setup?.entry_zone && setup.entry_zone.length >= 2) {
      const lo = Math.min(...setup.entry_zone);
      const hi = Math.max(...setup.entry_zone);
      priceLinesRef.current.push(
        series.createPriceLine({
          price: lo,
          color: "#60a5fa",
          lineWidth: 1,
          lineStyle: 1,
          axisLabelVisible: true,
          title: "Entry low",
        }),
      );
      priceLinesRef.current.push(
        series.createPriceLine({
          price: hi,
          color: "#60a5fa",
          lineWidth: 1,
          lineStyle: 1,
          axisLabelVisible: true,
          title: "Entry high",
        }),
      );
    }

    if (setup?.stop_loss != null) {
      priceLinesRef.current.push(
        series.createPriceLine({
          price: setup.stop_loss,
          color: "#ef4444",
          lineWidth: 2,
          lineStyle: 0,
          axisLabelVisible: true,
          title: "Stop Loss",
        }),
      );
    }

    setup?.take_profit?.forEach((price, i) => {
      priceLinesRef.current.push(
        series.createPriceLine({
          price,
          color: "#10b981",
          lineWidth: 2,
          lineStyle: 0,
          axisLabelVisible: true,
          title: `TP${i + 1}`,
        }),
      );
    });

    const invLevel =
      setup?.invalidation_level ??
      levels?.invalidation_level ??
      setup?.stop_loss;
    if (invLevel != null) {
      priceLinesRef.current.push(
        series.createPriceLine({
          price: invLevel,
          color: "#f97316",
          lineWidth: 2,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "Invalidation",
        }),
      );
    }

    chart.timeScale().fitContent();
  }, [bars, annotations]);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[#212121] overflow-hidden flex flex-col h-full min-h-[220px]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border)] bg-[#1a1a1a] shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--text)]">XAU/USD</span>
          {annotations?.levels?.trend ? (
            <span className="text-xs px-2 py-0.5 rounded-full bg-[#2f2f2f] text-[var(--text-secondary)] border border-[var(--border)]">
              {annotations.levels.trend}
            </span>
          ) : null}
        </div>
        <div className="flex gap-1">
          {CHART_INTERVALS.map((iv) => (
            <button
              key={iv}
              type="button"
              onClick={() => setInterval(iv)}
              className={`px-2 py-0.5 text-xs rounded border ${
                interval === iv
                  ? "bg-[#ececec] text-[#171717] border-[#ececec]"
                  : "bg-transparent text-[var(--text-secondary)] border-[var(--border)] hover:bg-[#2f2f2f]"
              }`}
            >
              {iv}
            </button>
          ))}
        </div>
      </div>
      <div className="relative flex-1 min-h-[180px]">
        <div ref={containerRef} className="w-full h-full" />
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-[var(--text-secondary)] bg-[#212121]/80">
            Loading chart…
          </div>
        ) : null}
        {error ? (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-red-400 px-4 text-center bg-[#212121]">
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}
