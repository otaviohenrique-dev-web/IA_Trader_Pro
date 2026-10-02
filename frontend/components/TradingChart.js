"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  createChart, createSeriesMarkers, ColorType, CrosshairMode, LineStyle,
  CandlestickSeries, LineSeries,
} from "lightweight-charts";
import { Maximize2, Spline, Waves } from "lucide-react";
import { backendHttpBase } from "../lib/api";
import { fmtPrice, fmtPct } from "../lib/format";

const GAIN = "#34d399";
const LOSS = "#fb7185";
const GRID = "rgba(148,163,184,0.06)";
const AXIS = "rgba(148,163,184,0.15)";

/** ZigZag (topos e fundos) para destacar a estrutura do preço */
function calculateZigZag(data, thresholdPct = 0.8) {
  if (!data?.length) return [];
  const pivots = [];
  let last = { ...data[0] };
  let trend = 0;
  for (let i = 1; i < data.length; i++) {
    const c = data[i];
    const up = ((c.high - last.low) / last.low) * 100;
    const down = ((last.high - c.low) / last.high) * 100;
    if (trend !== 1 && up >= thresholdPct) {
      pivots.push({ time: last.time, value: last.low });
      last = c; trend = 1;
    } else if (trend !== -1 && down >= thresholdPct) {
      pivots.push({ time: last.time, value: last.high });
      last = c; trend = -1;
    } else {
      if (trend === 1 && c.high > last.high) last = c;
      if (trend === -1 && c.low < last.low) last = c;
    }
  }
  pivots.push({ time: last.time, value: trend === 1 ? last.high : last.low });
  return pivots
    .filter((v, i, a) => v.value != null && !Number.isNaN(v.value) && a.findIndex((t) => t.time === v.time) === i)
    .sort((a, b) => a.time - b.time);
}

/** Converte os marcadores do backend para o formato do plugin de marcadores (v5) */
function toChartMarkers(markers) {
  return [...(markers || [])]
    .sort((a, b) => a.time - b.time)
    .map((m) => {
      if (m.shape === "circle") {
        const long = m.text.includes("COMPRA");
        return {
          time: m.time, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown",
          color: long ? GAIN : LOSS, text: long ? "COMPRA" : "VENDA", size: 1.4,
        };
      }
      const win = m.text.includes("GANHO");
      return { time: m.time, position: "aboveBar", shape: "circle", color: win ? GAIN : LOSS, text: win ? "GANHO" : "PERDA", size: 1 };
    });
}

export default function TradingChart({ asset = "BTC", liveCandle, markersData, position, ema50, ema200 }) {
  const containerRef = useRef(null);
  const tooltipRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const markersPluginRef = useRef(null);
  const zigzagRef = useRef(null);
  const tradeLineRef = useRef(null);
  const dataMap = useRef(new Map());
  const markersRef = useRef([]);
  const linesRef = useRef({});
  const lastHoverTime = useRef(null);

  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState(null);
  const [showZigzag, setShowZigzag] = useState(true);
  const [showEma, setShowEma] = useState(true);

  useEffect(() => { markersRef.current = markersData || []; }, [markersData]);

  // ---------- criação do gráfico (uma vez) ----------
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0b1120" }, textColor: "#8a97ad",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", fontSize: 11,
      },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(148,163,184,0.35)", labelBackgroundColor: "#1e293b" },
        horzLine: { color: "rgba(148,163,184,0.35)", labelBackgroundColor: "#1e293b" },
      },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: AXIS, rightOffset: 6 },
      rightPriceScale: { borderColor: AXIS, scaleMargins: { top: 0.1, bottom: 0.1 } },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: GAIN, downColor: LOSS, borderVisible: false, wickUpColor: GAIN, wickDownColor: LOSS,
    });
    const zigzag = chart.addSeries(LineSeries, {
      color: "rgba(56,189,248,0.55)", lineWidth: 1, lineStyle: LineStyle.Dashed,
      crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
    });
    const tradeLine = chart.addSeries(LineSeries, {
      color: "#a78bfa", lineWidth: 2, lineStyle: LineStyle.Dotted, lastValueVisible: false,
      priceLineVisible: false, crosshairMarkerVisible: true, autoscaleInfoProvider: () => null,
    });

    chartRef.current = chart;
    seriesRef.current = series;
    zigzagRef.current = zigzag;
    tradeLineRef.current = tradeLine;
    markersPluginRef.current = createSeriesMarkers(series, []);

    let cancelled = false;
    let retry = null;
    const loadHistory = async () => {
      try {
        const res = await fetch(`${backendHttpBase()}/api/historico?asset=${asset}`);
        const data = res.ok ? await res.json() : [];
        if (cancelled) return;
        const candles = (data || [])
          .filter((c) => c.time != null && [c.open, c.high, c.low, c.close].every((v) => v != null && !Number.isNaN(v)))
          .sort((a, b) => a.time - b.time)
          .filter((c, i, a) => i === 0 || c.time !== a[i - 1].time);
        if (!candles.length) throw new Error("sem candles");
        candles.forEach((c) => dataMap.current.set(c.time, c));
        series.setData(candles);
        zigzag.setData(calculateZigZag(candles));
        chart.timeScale().fitContent();
        setReady(true);
      } catch (err) {
        if (!cancelled) retry = setTimeout(loadHistory, 5000); // servidor free pode estar acordando
      }
    };
    loadHistory();

    chart.subscribeCrosshairMove((param) => {
      const tip = tooltipRef.current;
      const t = param.time ?? null;
      const candle = t ? param.seriesData.get(series) : null;
      if (t !== lastHoverTime.current) {
        lastHoverTime.current = t;
        setHover(candle && candle.open != null ? { time: t, ...candle } : null);
      }
      if (!tip) return;
      const marker = t ? markersRef.current.find((m) => m.time === t) : null;
      if (!marker || !candle || !param.point) {
        tip.style.display = "none";
        tradeLine.setData([]);
        return;
      }
      const isEntry = marker.shape === "circle";
      const px = Number(candle.close);
      tip.style.display = "block";
      tip.style.left = `${Math.min(param.point.x + 16, el.clientWidth - 190)}px`;
      tip.style.top = `${Math.max(param.point.y - 10, 8)}px`;
      const long = marker.text.includes("COMPRA");
      tip.innerHTML = isEntry
        ? `<div class="eyebrow" style="color:${long ? GAIN : LOSS}">Entrada ${long ? "comprada (long)" : "vendida (short)"}</div>
           <div class="num" style="font-size:13px;margin-top:4px">US$ ${fmtPrice(px)}</div>`
        : `<div class="eyebrow" style="color:${marker.text.includes("GANHO") ? GAIN : LOSS}">Saída · ${marker.text.includes("GANHO") ? "ganho" : "perda"}</div>
           <div class="num" style="font-size:13px;margin-top:4px">US$ ${fmtPrice(px)}</div>`;

      const sorted = [...markersRef.current].sort((a, b) => a.time - b.time);
      const entry = isEntry ? marker : [...sorted].reverse().find((m) => m.time < t && m.shape === "circle");
      const exit = isEntry ? sorted.find((m) => m.time > t && m.shape === "square") : marker;
      const e = entry && dataMap.current.get(entry.time);
      const x = exit && dataMap.current.get(exit.time);
      if (e && x && exit.time > entry.time) tradeLine.setData([{ time: entry.time, value: e.close }, { time: exit.time, value: x.close }]);
      else tradeLine.setData([]);
    });

    return () => {
      cancelled = true;
      if (retry) clearTimeout(retry);
      chart.remove();
      chartRef.current = seriesRef.current = zigzagRef.current = tradeLineRef.current = markersPluginRef.current = null;
      linesRef.current = {};
    };
  }, [asset]);

  // ---------- vela ao vivo ----------
  useEffect(() => {
    if (!ready || !seriesRef.current || !liveCandle?.time) return;
    const { time, open, high, low, close } = liveCandle;
    if ([open, high, low, close].some((v) => v == null || Number.isNaN(v))) return;
    dataMap.current.set(time, { time, open, high, low, close });
    try { seriesRef.current.update({ time, open, high, low, close }); } catch (_) { /* vela antiga */ }
  }, [liveCandle, ready]);

  // ---------- marcadores de entrada/saída ----------
  useEffect(() => {
    if (!ready || !markersPluginRef.current) return;
    try { markersPluginRef.current.setMarkers(toChartMarkers(markersData)); } catch (_) { /* ignora */ }
  }, [markersData, ready]);

  const setLine = (key, price, opts) => {
    const s = seriesRef.current;
    if (!s) return;
    if (linesRef.current[key]) { try { s.removePriceLine(linesRef.current[key]); } catch (_) {} linesRef.current[key] = null; }
    if (price > 0) linesRef.current[key] = s.createPriceLine({ price, axisLabelVisible: true, lineWidth: 1, ...opts });
  };

  // ---------- linhas da posição aberta: entrada, stop e alvo (valores reais da posição) ----------
  const pEntry = position?.entry || 0, pStop = position?.stop || 0, pTp = position?.tp || 0;
  useEffect(() => {
    if (!ready) return;
    setLine("entry", pEntry, { color: "#fbbf24", lineWidth: 2, lineStyle: LineStyle.Solid, title: "ENTRADA" });
    setLine("sl", pStop, { color: LOSS, lineStyle: LineStyle.Dashed, title: "STOP" });
    setLine("tp", pTp, { color: GAIN, lineStyle: LineStyle.Dashed, title: "ALVO" });
  }, [ready, pEntry, pStop, pTp]);

  // ---------- médias macro 4H ----------
  const e50 = ema50 ? Number(ema50.toPrecision(5)) : 0;
  const e200 = ema200 ? Number(ema200.toPrecision(5)) : 0;
  useEffect(() => {
    if (!ready) return;
    setLine("ema50", showEma ? e50 : 0, { color: "rgba(56,189,248,0.7)", lineStyle: LineStyle.SparseDotted, title: "EMA50 4H" });
    setLine("ema200", showEma ? e200 : 0, { color: "rgba(167,139,250,0.8)", lineStyle: LineStyle.SparseDotted, title: "EMA200 4H" });
  }, [ready, showEma, e50, e200]);

  useEffect(() => { zigzagRef.current?.applyOptions({ visible: showZigzag }); }, [showZigzag, ready]);

  // ---------- legenda ----------
  const shown = hover || liveCandle;
  const chg = shown?.open ? ((shown.close - shown.open) / shown.open) * 100 : 0;
  const up = chg >= 0;
  const inPosition = pEntry > 0;
  const floating = inPosition && liveCandle?.close ? ((liveCandle.close - pEntry) / pEntry) * 100 : 0;

  const toggle = (on) =>
    `pointer-events-auto flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition-colors ${
      on ? "border-accent/40 bg-accent/10 text-accent" : "border-line bg-panel/80 text-slate-400 hover:text-slate-200"
    }`;

  return (
    <div className="relative h-full min-h-[440px] sm:min-h-[540px]">
      <div className="pointer-events-none absolute left-3 top-3 z-10 max-w-[50%] sm:max-w-[70%]">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-sm font-bold text-white">{asset}/USDT</span>
          <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400">4H</span>
          {shown?.close != null && (
            <span className={`num text-xs font-semibold ${up ? "text-gain" : "text-loss"}`}>{fmtPct(chg)}</span>
          )}
        </div>
        {shown?.close != null && (
          <div className="num mt-1 flex flex-wrap gap-x-3 text-[11px] text-slate-400">
            <span>A <b className="font-semibold text-slate-200">{fmtPrice(shown.open)}</b></span>
            <span>M <b className="font-semibold text-slate-200">{fmtPrice(shown.high)}</b></span>
            <span>m <b className="font-semibold text-slate-200">{fmtPrice(shown.low)}</b></span>
            <span>F <b className="font-semibold text-slate-200">{fmtPrice(shown.close)}</b></span>
          </div>
        )}
      </div>

      <div className="pointer-events-none absolute right-[78px] top-3 z-10 flex items-center gap-2">
        {inPosition && (
          <span className={`num mr-1 hidden rounded-lg border px-2.5 py-1.5 sm:inline text-[11px] font-bold ${
            floating >= 0 ? "border-gain/40 bg-gain/10 text-gain" : "border-loss/40 bg-loss/10 text-loss"}`}>
            COMPRADO {fmtPct(floating)}
          </span>
        )}
        <button type="button" className={toggle(showEma)} onClick={() => setShowEma((v) => !v)} title="Médias macro 4H">
          <Waves size={13} /> <span className="hidden sm:inline">Médias 4H</span>
        </button>
        <button type="button" className={toggle(showZigzag)} onClick={() => setShowZigzag((v) => !v)} title="ZigZag">
          <Spline size={13} /> <span className="hidden sm:inline">ZigZag</span>
        </button>
        <button type="button" className={toggle(false)} onClick={() => chartRef.current?.timeScale().fitContent()} title="Ajustar ao conteúdo">
          <Maximize2 size={13} />
        </button>
      </div>

      {!ready && (
        <div className="absolute inset-0 z-10 flex items-center justify-center text-xs text-slate-500">
          <span className="animate-pulse">Carregando velas do mercado…</span>
        </div>
      )}

      <div ref={containerRef} className="absolute inset-0" />
      <div
        ref={tooltipRef}
        className="pointer-events-none absolute z-20 w-44 rounded-lg border border-white/10 bg-ink/90 p-3 shadow-xl backdrop-blur"
        style={{ display: "none" }}
      />
    </div>
  );
}
