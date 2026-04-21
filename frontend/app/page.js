"use client";

import React, { useState, useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts'; 
import { Activity, CircleDot, Clock, Zap, Brain, ShieldAlert, Wallet, List, Bitcoin, Download, Upload, Key, Database, Github, Linkedin } from 'lucide-react';
import NewsSentinel from '../components/NewsSentinel';

/** HTTP base do FastAPI (ex.: http://127.0.0.1:10000). Opcional: NEXT_PUBLIC_API_URL */
function backendHttpBase() {
  const api = process.env.NEXT_PUBLIC_API_URL;
  if (api) return api.replace(/\/$/, "");
  const ws = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:10000/ws";
  return ws
    .replace(/^wss:\/\//i, "https://")
    .replace(/^ws:\/\//i, "http://")
    .replace(/\/ws\/?$/i, "");
}

/** WebSocket do backend (termina em /ws). Opcional: NEXT_PUBLIC_WS_URL */
function backendWsUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  const api = process.env.NEXT_PUBLIC_API_URL;
  if (api) {
    const u = api.replace(/\/$/, "");
    const host = u.includes("://") ? u.split("://")[1] : u;
    if (/^https:/i.test(u)) return `wss://${host}/ws`;
    return `ws://${host}/ws`;
  }
  return "ws://127.0.0.1:10000/ws";
}

// ==========================================
// 🧮 FUNÇÃO ZIGZAG (Topos e Fundos)
// ==========================================
const calculateZigZag = (data, thresholdPct = 0.5) => {
  if (!data || data.length === 0) return [];
  let pivots = [];
  let lastPivot = { ...data[0], type: 'none' };
  let trend = 0; 

  for (let i = 1; i < data.length; i++) {
    const candle = data[i];
    const changeHigh = ((candle.high - lastPivot.low) / lastPivot.low) * 100;
    const changeLow = ((lastPivot.high - candle.low) / lastPivot.high) * 100;

    if (trend !== 1 && changeHigh >= thresholdPct) {
      pivots.push({ time: lastPivot.time, value: lastPivot.low });
      lastPivot = candle;
      trend = 1;
    } else if (trend !== -1 && changeLow >= thresholdPct) {
      pivots.push({ time: lastPivot.time, value: lastPivot.high });
      lastPivot = candle;
      trend = -1;
    } else {
      if (trend === 1 && candle.high > lastPivot.high) lastPivot = candle;
      if (trend === -1 && candle.low < lastPivot.low) lastPivot = candle;
    }
  }
  pivots.push({ time: lastPivot.time, value: trend === 1 ? lastPivot.high : lastPivot.low });
  return pivots.filter((v, i, a) => a.findIndex(t => t.time === v.time) === i).sort((a, b) => a.time - b.time);
};

/** Marcadores de entrada com preço Y exato (lightweight-charts v5). */
function prepareChartMarkers(markers, candleByTime) {
  if (!markers?.length) return [];
  return markers.map((m) => {
    if (m.shape !== "circle") return m;
    const c = candleByTime.get(m.time);
    const price = m.price != null ? Number(m.price) : (c?.close != null ? Number(c.close) : null);
    if (price == null || Number.isNaN(price)) return m;
    const size = Math.max(3, Number(m.size) || 3);
    return { ...m, position: "atPriceMiddle", price, size };
  });
}

/**
 * Linha horizontal no preço de entrada: do candle de entrada até o de saída (ou até o candle ao vivo se aberto).
 * Usa Whitespace entre segmentos para não ligar trades diferentes.
 */
function buildEntryHorizontalLineData(markers, liveCandle, inPosition, entryPriceState, candleMap) {
  if (!markers?.length) return [];
  const sorted = [...markers].sort((a, b) => a.time - b.time);
  const circles = sorted.filter((m) => m.shape === "circle");
  if (circles.length === 0) return [];

  const segments = [];
  for (const ent of circles) {
    let px = ent.price != null ? Number(ent.price) : null;
    if (px == null || Number.isNaN(px)) {
      const c = candleMap.get(ent.time);
      if (c?.close != null) px = Number(c.close);
    }
    if (px == null || Number.isNaN(px)) continue;

    const exit = sorted.find((m) => m.shape === "square" && m.time > ent.time);
    if (exit) {
      segments.push({ t0: ent.time, t1: exit.time, price: px });
    } else {
      let endT = liveCandle?.time != null ? Number(liveCandle.time) : ent.time;
      if (inPosition && entryPriceState > 0) px = Number(entryPriceState);
      if (endT <= ent.time) endT = ent.time + 900;
      segments.push({ t0: ent.time, t1: endT, price: px });
    }
  }

  const out = [];
  segments.forEach((s, i) => {
    if (i > 0) out.push({ time: segments[i - 1].t1 });
    out.push({ time: s.t0, value: s.price });
    out.push({ time: s.t1, value: s.price });
  });
  return out;
}

// ==========================================
// 🧬 COMPONENTE: DOJO (PROTOCOLO APOCALIPSE)
// ==========================================
function DojoPanel({ state }) {
  const [senha, setSenha] = useState('');
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mensagem, setMensagem] = useState('');

  const API_URL = backendHttpBase();

  const handleDownload = async () => {
    if (!senha) { setMensagem('⚠️ Digite a senha Admin.'); return; }
    setMensagem('⏳ Gerando arquivo...');
    
    try {
      // Faz o request enviando a senha de forma invisível no Header
      const res = await fetch(`${API_URL}/download-dados`, {
        method: 'GET',
        headers: { 'x-admin-password': senha }
      });
      
      if (!res.ok) throw new Error('Senha incorreta ou arquivo inexistente.');
      
      // Cria um link temporário na memória para forçar o download
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `historico_bot_${Date.now()}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      
      setMensagem('✅ Download Concluído!');
    } catch (err) {
      setMensagem(`❌ Erro: ${err.message}`);
    }
  };

  const handleUpload = async () => {
    if (!senha || !file) { setMensagem('⚠️ Chave ou arquivo ausente.'); return; }
    setLoading(true);
    setMensagem('⏳ Injetando...');
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
      // Remove o ?senha= e passa para o Header
      const res = await fetch(`${API_URL}/upload-cerebro`, { 
        method: 'POST', 
        headers: { 'x-admin-password': senha },
        body: formData 
      });
      
      if (res.ok) { 
        setMensagem('✅ Geração Injetada!'); 
        setFile(null); 
      } else { 
        setMensagem('❌ Acesso Negado (Senha Incorreta).'); 
      }
    } catch (err) { 
      setMensagem('❌ Erro de Conexão.'); 
    }
    setLoading(false);
  };

  return (
    <div className="bg-slate-800/50 p-6 rounded-xl border border-purple-500/30 shadow-lg mt-6">
      <h2 className="text-xl font-bold text-purple-400 mb-4 flex items-center gap-2 border-b border-purple-900/50 pb-3">
        <Brain size={24} /> Laboratório Neural (Dojo)
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="space-y-3 bg-slate-900/50 p-4 rounded-lg border border-slate-700">
          <label className="text-xs font-semibold text-slate-400 flex items-center gap-2 uppercase tracking-widest"><Key size={14}/> Chave de Autorização</label>
          <input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} className="w-full bg-slate-800 border border-slate-600 rounded p-2 text-white font-mono text-sm" placeholder="••••••••" />
          {mensagem && <div className="text-[10px] font-mono text-center p-1 bg-purple-500/10 text-purple-300 rounded border border-purple-500/20">{mensagem}</div>}
        </div>
        <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700 flex flex-col justify-between min-h-[140px]">
           <label className="text-xs font-semibold text-slate-400 flex items-center gap-2 mb-2 uppercase tracking-widest"><Database size={14}/> Coleta de Dados</label>
           <button onClick={handleDownload} className="w-full bg-blue-600/20 hover:bg-blue-600/40 text-blue-400 border border-blue-500/50 py-2 rounded text-xs font-bold transition-all mt-auto">EXPORTAR HISTÓRICO (CSV)</button>
        </div>
        <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700 flex flex-col justify-between min-h-[140px]">
           <label className="text-xs font-semibold text-slate-400 flex items-center gap-2 mb-2 uppercase tracking-widest"><Upload size={14}/> Nova Geração</label>
           <input type="file" accept=".zip" onChange={(e) => setFile(e.target.files ? e.target.files[0] : null)} className="text-[10px] text-slate-400 mb-2" />
           <button onClick={handleUpload} disabled={loading || !file} className="w-full bg-purple-600 hover:bg-purple-500 text-white py-2 rounded text-xs font-bold shadow-lg shadow-purple-500/20 transition-all mt-auto">APLICAR CÉREBRO</button>
        </div>
      </div>
    </div>
  );
}

// ==========================================
// 📈 COMPONENTE DE GRÁFICO (COM LINHA DE ENTRADA)
// ==========================================
function TradingChart({ liveCandle, markersData, inPosition, entryPrice, currentPosition }) {
  const chartContainerRef = useRef(null);
  const tooltipRef = useRef(null);
  const chartInstance = useRef(null);
  const seriesInstance = useRef(null);
  const zigzagSeriesRef = useRef(null);
  const exactTradeLineRef = useRef(null);
  const entryHorizontalSeriesRef = useRef(null);

  const isDataLoaded = useRef(false);
  const markersRef = useRef([]);
  const chartDataMap = useRef(new Map());
  const currentHoverState = useRef("none");
  const markersSigRef = useRef("");

  useEffect(() => {
    if (markersData) markersRef.current = markersData;
  }, [markersData]);

  useEffect(() => {
    if (!chartContainerRef.current || chartInstance.current) return;

    const initialWidth = chartContainerRef.current.clientWidth || 800;

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: 'rgba(30, 41, 59, 0.4)' }, horzLines: { color: 'rgba(30, 41, 59, 0.4)' } },
      width: initialWidth,
      height: 450,
      crosshair: { mode: 0 }, 
      timeScale: { timeVisible: true, borderColor: '#334155' },
      rightPriceScale: { borderColor: '#334155' },
    });

    const newSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#1e293b', downColor: '#1e293b', borderUpColor: '#334155', borderDownColor: '#334155', wickUpColor: '#334155', wickDownColor: '#334155',
    });

    const zigzagSeries = chart.addSeries(LineSeries, {
      color: '#38bdf8', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
    });

    const exactTradeLine = chart.addSeries(LineSeries, {
      color: '#a855f7', lineWidth: 2, lineStyle: 3, crosshairMarkerVisible: true, lastValueVisible: false, priceLineVisible: false, autoscaleInfoProvider: () => null 
    });

    const entryHorizontal = chart.addSeries(LineSeries, {
      color: "#fbbf24",
      lineWidth: 2,
      lineStyle: 2,
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
    });

    chartInstance.current = chart;
    seriesInstance.current = newSeries;
    zigzagSeriesRef.current = zigzagSeries;
    exactTradeLineRef.current = exactTradeLine;
    entryHorizontalSeriesRef.current = entryHorizontal;

    const carregarHistorico = async () => {
      const API_URL = backendHttpBase();
      
      try {
        const res = await fetch(`${API_URL}/api/historico`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.length > 0) {
            const unique = [...data].sort((a, b) => a.time - b.time).filter((v, i, a) => a.findIndex(t => (t.time === v.time)) === i);
            unique.forEach(candle => chartDataMap.current.set(candle.time, candle));

            const dimmedData = unique.map(candle => {
              const marker = markersRef.current.find(m => m.time === candle.time);
              if (marker) return { ...candle, color: marker.color, wickColor: marker.color, borderColor: marker.color };
              return candle; 
            });

            newSeries.setData(dimmedData);
            zigzagSeries.setData(calculateZigZag(dimmedData, 0.8));
            chart.timeScale().fitContent();
            isDataLoaded.current = true;
            markersSigRef.current = "";
            if (markersRef.current.length > 0 && typeof newSeries.setMarkers === "function") {
              const sorted = [...markersRef.current].sort((a, b) => a.time - b.time);
              newSeries.setMarkers(prepareChartMarkers(sorted, chartDataMap.current));
              markersSigRef.current = JSON.stringify(sorted);
            }
            if (entryHorizontalSeriesRef.current) {
              const hData = buildEntryHorizontalLineData(
                markersRef.current,
                null,
                false,
                0,
                chartDataMap.current
              );
              try {
                entryHorizontalSeriesRef.current.setData(hData);
              } catch (_) { /* noop */ }
            }
          }
        }
      } catch (err) { console.error("Erro API:", err); }
    };

    carregarHistorico();

    let requestAnimationFrameId = null;
    chart.subscribeCrosshairMove((param) => {
      // (Mantivemos sua lógica impecável de Tooltip aqui, reduzida visualmente para focar no novo recurso)
      if (requestAnimationFrameId) cancelAnimationFrame(requestAnimationFrameId);
      requestAnimationFrameId = requestAnimationFrame(() => {
        const tooltip = tooltipRef.current;
        if (!param.time || param.point.x < 0 || param.point.y < 0 || !tooltip) {
          tooltip.style.display = 'none';
          if (currentHoverState.current !== "none") { exactTradeLine.setData([]); currentHoverState.current = "none"; }
          return;
        }

        const hoveredMarker = markersRef.current.find(m => m.time === param.time);
        const candleData = chartDataMap.current.get(param.time) || param.seriesData.get(newSeries);

        if (hoveredMarker && candleData) {
          tooltip.style.display = 'block';
          tooltip.style.left = param.point.x + 15 + 'px';
          tooltip.style.top = param.point.y + 15 + 'px';
          
          const isEntry = hoveredMarker.shape === 'circle';
          const direction = hoveredMarker.text.includes('COMPRA') ? '⬆️ Compra (long)' : '⬇️ Venda (short)';
          const result = hoveredMarker.text.includes('GANHO') ? '✅ Ganho' : (hoveredMarker.text.includes('PERDA') ? '❌ Perda' : '');
          const rsiText = candleData.rsi ? candleData.rsi.toFixed(2) : 'Aguardando...';
          const bbText = candleData.bb_width ? candleData.bb_width.toFixed(2) : 'Aguardando...';

          tooltip.innerHTML = `
            <div class="font-bold text-sm mb-1 ${hoveredMarker.color === '#22c55e' ? 'text-green-400' : 'text-red-400'}">
              ${isEntry ? 'ESTADO IA: ENTRADA' : 'ESTADO IA: SAÍDA'}
            </div>
            <div class="text-xs text-white mb-1">Ação: ${isEntry ? direction : result}</div>
            <div class="text-xs text-slate-300">${isEntry ? "Preço de entrada" : "Preço (fechamento)"}: US$ ${(hoveredMarker.price != null ? Number(hoveredMarker.price) : candleData.close).toFixed(2)}</div>
            <div class="mt-2 pt-2 border-t border-slate-600 text-[10px] text-slate-400 font-mono">
              RSI: ${rsiText}<br/>BB Largura: ${bbText}
            </div>
          `;

          if (currentHoverState.current !== param.time) {
            currentHoverState.current = param.time; 
            if (isEntry) {
              const exitMarker = markersRef.current.find(m => m.time > param.time && m.shape === 'square');
              if (exitMarker && exitMarker.time !== param.time) {
                const exitCandle = chartDataMap.current.get(exitMarker.time);
                exactTradeLine.setData([{ time: param.time, value: hoveredMarker.price != null ? Number(hoveredMarker.price) : candleData.close }, { time: exitMarker.time, value: exitCandle ? exitCandle.close : candleData.close }]);
              }
            } else {
              const entryMarker = [...markersRef.current].reverse().find(m => m.time < param.time && m.shape === 'circle');
              if (entryMarker && entryMarker.time !== param.time) {
                const entryCandle = chartDataMap.current.get(entryMarker.time);
                exactTradeLine.setData([{ time: entryMarker.time, value: entryMarker.price != null ? Number(entryMarker.price) : (entryCandle ? entryCandle.close : candleData.close) }, { time: param.time, value: candleData.close }]);
              }
            }
          }
        } else {
          tooltip.style.display = 'none';
          if (currentHoverState.current !== "none") { exactTradeLine.setData([]); currentHoverState.current = "none"; }
        }
      });
    });

    const resizeObserver = new ResizeObserver(entries => {
      if (entries.length === 0 || !chartInstance.current) return;
      const { width, height } = entries[0].contentRect;
      chartInstance.current.applyOptions({ width, height });
    });
    resizeObserver.observe(chartContainerRef.current);

    return () => {
      if (requestAnimationFrameId) cancelAnimationFrame(requestAnimationFrameId);
      resizeObserver.disconnect();
      chart.remove();
      chartInstance.current = null;
      entryHorizontalSeriesRef.current = null;
    };
  }, []); 

  useEffect(() => {
    if (isDataLoaded.current && seriesInstance.current && liveCandle?.time) {
      chartDataMap.current.set(liveCandle.time, liveCandle); 
      let cColor = '#1e293b'; 
      const hasAction = markersRef.current.find(m => m.time === liveCandle.time);
      if (hasAction) cColor = hasAction.color; 
      try { seriesInstance.current.update({ ...liveCandle, color: cColor, wickColor: cColor, borderColor: cColor }); } catch (e) {}
    }
  }, [liveCandle]);

  useEffect(() => {
    if (!isDataLoaded.current || !seriesInstance.current || markersData == null) return;
    const sorted = [...markersData].sort((a, b) => a.time - b.time);
    const sig = JSON.stringify(sorted);
    if (sig === markersSigRef.current) return;
    markersSigRef.current = sig;
    try {
      if (typeof seriesInstance.current.setMarkers === "function") {
        seriesInstance.current.setMarkers(prepareChartMarkers(sorted, chartDataMap.current));
      }
    } catch (e) {
      console.error("Erro ao aplicar marcadores:", e);
    }
  }, [markersData]);

  /** Linha horizontal âmbar: preço de entrada do candle de entrada até saída ou candle atual. */
  useEffect(() => {
    if (!isDataLoaded.current || !entryHorizontalSeriesRef.current || markersData == null) return;
    const lineData = buildEntryHorizontalLineData(
      markersData,
      liveCandle,
      inPosition,
      entryPrice,
      chartDataMap.current
    );
    try {
      entryHorizontalSeriesRef.current.setData(lineData);
    } catch (e) {
      console.error("Erro linha entrada:", e);
    }
  }, [markersData, liveCandle, inPosition, entryPrice, currentPosition]);

  return (
    <div className="w-full relative rounded overflow-hidden" style={{ minHeight: '450px' }}>
      <div 
        ref={tooltipRef} 
        className="absolute z-50 bg-slate-900/90 backdrop-blur border border-purple-500/50 p-3 rounded shadow-lg pointer-events-none transition-opacity duration-100"
        style={{ display: 'none' }}
      ></div>
      <div ref={chartContainerRef} className="w-full h-[450px]"></div>
    </div>
  );
}

// ==========================================
// 📊 DASHBOARD PRINCIPAL
// ==========================================
export default function Dashboard() {
  const [data, setData] = useState(null);
  const [wsLive, setWsLive] = useState(false);
  const [previousState, setPreviousState] = useState(null);
  const ws = useRef(null);
  const reconnectRef = useRef(null);

  useEffect(() => {
    const httpBase = backendHttpBase();
    let cancelled = false;

    const pullState = async () => {
      try {
        const res = await fetch(`${httpBase}/api/state`);
        
        // Debug logging
        console.log(`[API] GET /api/state -> Status: ${res.status}, OK: ${res.ok}`);
        
        if (res.ok && !cancelled) {
            const text = await res.text();
            console.log(`[API] Response length: ${text.length} bytes`);
            
            if (!text) {
                setData({ error: "⚠️ API retornou resposta vazia (0 bytes)" });
                setWsLive(false);
                return;
            }
            
            try {
                const newState = JSON.parse(text);
                console.log(`[API] JSON parsed OK. Keys: ${Object.keys(newState).join(", ")}`);
                
                // Delta update: só atualiza se mudou
                if (!previousState || JSON.stringify(previousState) !== JSON.stringify(newState)) {
                    setData(newState);
                    setPreviousState(newState);
                }
                setWsLive(true);
            } catch (jsonErr) {
                console.error(`[API] JSON Parse Error:`, jsonErr);
                setData({ error: `❌ Resposta inválida da API (JSON quebrado): ${jsonErr.message}` });
                setWsLive(false);
            }
        } else {
            const bodyPreview = await res.text().catch(() => "[não legível]");
            console.error(`[API] Error Response:`, { status: res.status, body: bodyPreview.substring(0, 200) });
            setData({ error: `❌ Servidor retornou HTTP ${res.status}. Pode estar iniciando ou offline.` });
            setWsLive(false);
        }
      } catch (err) { 
        if (!cancelled) {
            console.error(`[API] Network/CORS Error:`, err);
            setData({ error: `❌ Erro de rede/CORS: ${err.message}` });
            setWsLive(false); 
        }
      }
    };

    pullState();

    const poll = setInterval(() => {
      if (cancelled) return;
      pullState();
    }, 5000); // ⚡ Reduzido de 2000ms para 5000ms (melhor performance)

    return () => {
      cancelled = true;
      clearInterval(poll);
    };
  }, [previousState]);

  if (!data) return (
    <div className="min-h-screen bg-[#0f172a] flex flex-col items-center justify-center text-white font-mono">
      <Activity className="animate-spin mb-4 text-blue-500" size={48} /> 
      <p className="animate-pulse">Sincronizando com o núcleo...</p>
    </div>
  );

  if (!data || data.error) return (
    <div className="min-h-screen bg-[#0f172a] flex flex-col items-center justify-center text-white font-mono px-6 text-center max-w-lg">
      <ShieldAlert className="mb-4 text-amber-500" size={48} />
      <p className="text-lg font-bold text-white mb-2">Servidor não respondeu</p>
      <p className="text-sm text-slate-400 mb-4">
        O painel não conseguiu alcançar a API Python. Verifique se a variável <code className="text-cyan-400">NEXT_PUBLIC_API_URL</code> no seu painel da Vercel está configurada corretamente para o Render.
      </p>
      <p className="text-xs text-slate-500 font-mono break-all">Endereço tentado: {backendHttpBase()}</p>
      {data?.error && <p className="text-xs text-red-400 mt-4 border border-red-500/30 bg-red-500/10 p-2 rounded">Erro no Backend: {data.error}</p>}
    </div>
  );

  const remainingSeconds = parseInt(data?.status?.match(/\d+/)?.[0] || 0);

  return (
    <div className="min-h-screen bg-[#0f172a] p-6 text-slate-100 font-sans">
      <header className="flex justify-between items-center mb-6 border-b border-slate-700/50 pb-4">
        <h1 className="text-3xl font-black flex items-center gap-3 italic">
          <Activity className="text-blue-500" /> IA TRADER PRO 
          <span className="text-[10px] not-italic bg-blue-500/10 border border-blue-500/30 px-2 py-1 rounded text-blue-400">V3.0.1</span>
        </h1>
        <div className="flex flex-col items-end gap-1">
          {!wsLive && (
            <span className="text-[10px] font-mono text-amber-400 border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 rounded">
              Aguardando conexão com API...
            </span>
          )}
          {wsLive && (
            <span className="text-[10px] font-mono text-green-400 border border-green-500/30 bg-green-500/10 px-2 py-0.5 rounded">
              Sincronizado (Tempo Real)
            </span>
          )}
          <div className="bg-slate-800 px-4 py-2 rounded-lg border border-slate-700 font-mono text-xs flex items-center gap-2">
            <Clock size={14} className="text-blue-400"/> Tempo ativo: {data.uptime}
          </div>
        </div>
      </header>

     {/* GRID DE CARDS */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
        
        {/* Ativo */}
        <div className="bg-slate-800/50 p-5 rounded-xl border border-slate-700/50 shadow-lg flex flex-col justify-between min-h-[140px]">
          <div className="text-slate-400 text-xs font-bold uppercase tracking-widest flex items-center gap-2">
            <Bitcoin size={16} className="text-orange-500"/> Ativo
          </div>
          <div className="text-3xl lg:text-4xl font-black mt-auto font-mono uppercase text-white">
            {data.asset}
          </div>
        </div>

        {/* Card 2: Saldo Dinâmico */}
        <div className="bg-slate-800/50 p-5 rounded-xl border border-slate-700/50 shadow-lg relative overflow-hidden flex flex-col justify-between min-h-[140px]">
          {data.in_position && (
            <div className={`absolute top-0 right-0 w-1.5 h-full ${data.floating_pnl >= 0 ? 'bg-green-500' : 'bg-red-500'} animate-pulse`} />
          )}
          
          <div className="text-slate-400 text-xs font-bold uppercase tracking-widest flex items-center gap-2">
            <Wallet size={16}/> Patrimônio
          </div>

          <div className="mt-auto">
            <div className={`text-3xl lg:text-4xl font-black font-mono ${data.floating_pnl > 0 ? 'text-green-400' : data.floating_pnl < 0 ? 'text-red-400' : 'text-white'}`}>
              ${(data.display_balance || data.balance || 0).toFixed(2)}
            </div>
            {data.in_position && (
              <div className={`text-xs font-mono font-bold mt-1 ${data.floating_pnl >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                {data.floating_pnl >= 0 ? '▲' : '▼'} ${(data.floating_pnl || 0).toFixed(2)}
              </div>
            )}
          </div>
        </div>

        {/* Status / Cronômetro */}
        <div className={`p-5 rounded-xl border shadow-lg transition-all duration-500 flex flex-col justify-between min-h-[140px] ${data.status.includes("PROTEÇÃO") ? 'border-blue-500 bg-blue-500/10' : 'border-slate-700 bg-slate-800/50'}`}>
          <div className="text-slate-400 text-xs font-bold uppercase tracking-widest flex items-center gap-2">
            <Zap size={16} className={data.status.includes("PROTEÇÃO") ? "text-blue-400 animate-pulse" : ""}/> 
            Status Operacional
          </div>
          
          <div className="mt-auto">
            <div className="text-lg lg:text-xl font-bold uppercase tracking-tighter text-white">
            {data?.status?.includes("PROTEÇÃO") ? "Trava de Maturação" : data?.status}
            </div>
          {data?.status?.includes("PROTEÇÃO") && (
              <div className="mt-3 w-full">
                <div className="flex justify-between text-xs font-mono text-blue-400 mb-1.5">
                  <span>{remainingSeconds} s restantes</span>
                  <span>900 s</span>
                </div>
                <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                   <div className="h-full bg-blue-500 transition-all duration-1000 ease-linear" style={{ width: `${(remainingSeconds / 900) * 100}%` }} />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* News */}
        <NewsSentinel data={data.news_agent} />

        {/* Protocolo */}
        <div className="bg-gradient-to-br from-purple-900/40 to-slate-900 p-5 rounded-xl border border-purple-500/30 shadow-lg flex flex-col justify-between min-h-[140px]">
          <div className="text-purple-300 text-xs font-bold uppercase tracking-widest flex items-center gap-2">
            <Brain size={16}/> Protocolo
          </div>
          <div className="mt-auto">
            <div className="text-3xl lg:text-4xl font-black font-mono text-white">
              GEN {data.adaptation.generation}
            </div>
            <div className="text-sm lg:text-base text-green-400 font-mono mt-1 font-bold">
              Acertos: {data.adaptation.current_win_rate}%
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-3 bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 shadow-lg">
          <TradingChart 
  liveCandle={data.last_candle} 
  markersData={data.markers} 
  inPosition={data.in_position} 
  entryPrice={data.entry_price} 
  currentPosition={data.current_position} 
/>
        </div>
        <div className="bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 h-[482px] flex flex-col shadow-lg custom-scrollbar">
          <h2 className="text-xs font-black mb-4 flex items-center gap-2 border-b border-slate-700 pb-2 uppercase tracking-widest shrink-0">
            <List size={16}/> Livro de Ações
          </h2>
          <div className="flex-1 overflow-y-auto pr-1">
            {data.order_book && data.order_book.length > 0 ? (
              <div className="space-y-2">
                {data.order_book.map((order, i) => (
                  <div key={i} className="bg-slate-900/50 p-2 rounded text-[10px] font-mono border border-slate-600/30 text-slate-300">
                    {order.text}
                  </div>
                ))}
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-500/50 space-y-3 pb-10">
                <Activity size={32} className="animate-pulse text-slate-600" />
                <span className="text-[10px] text-center px-4 font-mono uppercase tracking-widest">
                  Registro vazio.<br/>O Sniper está na espreita...
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      <DojoPanel state={data} />

      <footer className="mt-12 pt-8 border-t border-slate-700/60 flex flex-col md:flex-row items-center justify-between gap-6 text-slate-500 text-sm">
        <p className="text-center md:text-left leading-relaxed">
          © {new Date().getFullYear()}{' '}
          <span className="text-slate-400">Otávio Henrique Filgueiras dos Santos</span>
          <span className="block text-xs text-slate-600 mt-1">IA Trader Pro — monitoramento e simulação. Uso por sua conta e risco.</span>
        </p>
        <nav className="flex items-center gap-5" aria-label="Redes sociais">
          <a
            href="https://www.linkedin.com/in/otaviohenrique-dev/"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-slate-400 hover:text-[#0A66C2] transition-colors"
          >
            <Linkedin size={20} aria-hidden />
            <span className="text-xs font-semibold tracking-wide">LinkedIn</span>
          </a>
          <a
            href="https://github.com/otaviohenrique-dev-web"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors"
          >
            <Github size={20} aria-hidden />
            <span className="text-xs font-semibold tracking-wide">GitHub</span>
          </a>
        </nav>
      </footer>
    </div>
  );
}