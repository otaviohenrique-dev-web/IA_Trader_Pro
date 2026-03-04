"use client";

import React, { useState, useEffect, useRef } from 'react';
// 1. IMPORTAÇÕES DA V5: CandlestickSeries e createSeriesMarkers
import { createChart, ColorType, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts'; 
import { Activity, CircleDot, Clock, Zap, Brain, ShieldAlert, Wallet, List, Bitcoin } from 'lucide-react';

export default function Dashboard() {
  const [data, setData] = useState(null);
  const chartContainerRef = useRef(null);
  const chartInstance = useRef(null);
  const seriesInstance = useRef(null);
  // 2. NOVO REF PARA CONTROLAR O PLUGIN DE SETAS
  const markersPluginInstance = useRef(null); 
  const ws = useRef(null);

  useEffect(() => {
    const socketUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000/ws";
    ws.current = new WebSocket(socketUrl);
    
    ws.current.onmessage = (event) => {
      const message = JSON.parse(event.data);
      setData(message);

      if (seriesInstance.current) {
        if (message.last_candle?.time) {
          try {
            seriesInstance.current.update(message.last_candle);
          } catch (e) {}
        }
        
        // 3. ATUALIZANDO AS SETAS VIA PLUGIN (V5)
        if (message.markers && message.markers.length > 0 && markersPluginInstance.current) {
          try {
            const sortedMarkers = [...message.markers].sort((a, b) => a.time - b.time);
            markersPluginInstance.current.setMarkers(sortedMarkers);
          } catch (e) {
            console.error("Erro ao desenhar marcadores:", e);
          }
        }
      }
    };
    
    return () => { if (ws.current) ws.current.close(); };
  }, []);

  useEffect(() => {
    if (!chartContainerRef.current || !data || !data.chart_data || data.chart_data.length === 0) return;
    if (chartInstance.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#334155' },
      rightPriceScale: { borderColor: '#334155' },
    });

    // 4. CRIAÇÃO DA VELA NO FORMATO V5
    const newSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444', borderUpColor: '#22c55e', borderDownColor: '#ef4444', wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });

    // 5. INICIALIZA O PLUGIN DE MARCADORES E CONECTA NA VELA
    const markersPlugin = createSeriesMarkers(newSeries, []);
    markersPluginInstance.current = markersPlugin;

    try {
      const sorted = [...data.chart_data].sort((a, b) => a.time - b.time);
      const unique = sorted.filter((v, i, a) => a.findIndex(t => (t.time === v.time)) === i);
      newSeries.setData(unique);
      
      // Carrega as setas históricas no primeiro render da página
      if (data.markers && data.markers.length > 0) {
        const sortedMarkers = [...data.markers].sort((a, b) => a.time - b.time);
        markersPlugin.setMarkers(sortedMarkers);
      }

      chart.timeScale().fitContent();
    } catch (e) {
      console.error("Erro na renderização inicial:", e);
    }

    chartInstance.current = chart;
    seriesInstance.current = newSeries;

    const handleResize = () => chart.applyOptions({ width: chartContainerRef.current.clientWidth });
    window.addEventListener('resize', handleResize);
    
    return () => { 
      window.removeEventListener('resize', handleResize); 
      chart.remove(); 
      chartInstance.current = null; 
      seriesInstance.current = null;
      markersPluginInstance.current = null;
    };
  }, [data]);

  if (!data) return (
    <div className="min-h-screen bg-[#0f172a] flex flex-col items-center justify-center text-white font-mono">
      <Activity className="animate-spin mb-4 text-purple-500" size={48} /> 
      <p>Sincronizando com a Matrix...</p>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#0f172a] p-6 font-sans text-slate-100">
      
      {/* HEADER PRINCIPAL */}
      <header className="flex justify-between items-center mb-6 border-b border-slate-700/50 pb-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3 text-white">
            <Activity className="text-blue-500" /> 
            IA TRADER PRO 
            <span className="text-xs bg-slate-800 border border-slate-600 px-3 py-1 rounded-full text-slate-300 font-mono flex items-center gap-2">
              <CircleDot size={12} className={data.is_online ? "text-green-500 animate-pulse" : "text-red-500"} />
              ONLINE
            </span>
          </h1>
        </div>
        <div className="text-right flex items-center gap-4">
          <div className="text-slate-400 font-mono text-sm flex items-center gap-2 bg-slate-800 px-3 py-1 rounded-lg border border-slate-700">
             <Clock size={16} className="text-blue-400"/> Uptime: {data.uptime}
          </div>
        </div>
      </header>

      {/* CARDS DE INFORMAÇÃO */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
         
         <div className="bg-slate-800/50 p-5 rounded-xl border border-slate-700/50 flex flex-col justify-between shadow-lg">
            <div className="flex justify-between items-start mb-2">
              <div className="text-slate-400 text-sm font-semibold flex items-center gap-2"><Bitcoin size={16} className="text-orange-500"/> Ativo Operacional</div>
              <div className="text-xs bg-orange-500/20 text-orange-400 px-2 py-1 rounded border border-orange-500/30">Crypto</div>
            </div>
            <div className="text-2xl font-black font-mono tracking-tight text-white flex items-center gap-2 mt-2">
              Bitcoin <span className="text-sm text-slate-500 font-sans">{data.asset}</span>
            </div>
         </div>

         <div className="bg-slate-800/50 p-5 rounded-xl border border-slate-700/50 flex flex-col justify-between shadow-lg">
            <div className="flex justify-between items-start mb-2">
              <div className="text-slate-400 text-sm font-semibold flex items-center gap-2"><Wallet size={16}/> Saldo da Conta</div>
              <div className="text-xs bg-blue-500/20 text-blue-400 px-2 py-1 rounded border border-blue-500/30">Fictício</div>
            </div>
            <div className="text-3xl font-black font-mono tracking-tight">${data.balance.toFixed(2)}</div>
         </div>

         <div className={`bg-slate-800/50 p-5 rounded-xl border flex flex-col justify-between shadow-lg ${data.in_position ? 'border-yellow-500/50 bg-yellow-500/10' : 'border-slate-700/50'}`}>
            <div className="text-slate-400 text-sm font-semibold mb-2 flex items-center gap-2"><Zap size={16}/> Estado do Bot</div>
            <div className="text-lg font-bold text-white">{data.status}</div>
         </div>

         <div className="bg-gradient-to-br from-purple-900/40 to-slate-900 p-5 rounded-xl border border-purple-500/30 relative overflow-hidden shadow-lg shadow-purple-900/20">
            <div className="absolute top-0 right-0 p-3 opacity-20"><ShieldAlert size={64} /></div>
            <div className="text-purple-300 text-sm font-semibold mb-1 flex items-center gap-2 z-10 relative">
              <Brain size={16}/> Protocolo Apocalipse
            </div>
            <div className="flex items-end gap-3 z-10 relative mt-2">
              <div className="text-3xl font-black font-mono text-white">Gen {data.adaptation.generation}</div>
              <div className="text-xs font-mono text-green-400 flex items-center pb-1 bg-green-900/30 px-2 rounded">
                Win Rate: {data.adaptation.initial_win_rate}% ➔ {data.adaptation.current_win_rate}%
              </div>
            </div>
            <div className="text-xs text-purple-400/70 mt-2 z-10 relative font-mono uppercase tracking-wider">
              Status: {data.adaptation.learning_state}
            </div>
         </div>
      </div>

      {/* ÁREA PRINCIPAL */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-3 bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 shadow-lg flex flex-col">
           <div ref={chartContainerRef} className="w-full relative rounded overflow-hidden" style={{ height: '450px' }}>
           </div>
        </div>

        <div className="bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 h-[482px] flex flex-col shadow-lg">
           <h2 className="text-sm font-bold mb-3 text-slate-300 flex items-center gap-2 border-b border-slate-700 pb-2">
             <List size={16}/> Histórico de Ações
           </h2>
           <div className="flex-1 overflow-auto pr-1 custom-scrollbar">
             {data.order_book && data.order_book.length > 0 ? (
               <div className="space-y-2">
                 {data.order_book.map((order, i) => (
                   <div key={i} className="bg-slate-700/30 p-2 rounded border border-slate-600/30 text-xs font-mono">
                      {order.text}
                   </div>
                 ))}
               </div>
             ) : (
               <div className="h-full flex flex-col items-center justify-center text-slate-500 space-y-2 opacity-50">
                 <ShieldAlert size={32} />
                 <span className="text-xs text-center px-4">O livro de ofertas está vazio. Aguardando a primeira ordem.</span>
               </div>
             )}
           </div>
        </div>
      </div>
    </div>
  );
}