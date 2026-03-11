"use client";

import React, { useState, useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts';
import { Activity, CircleDot, Clock, Zap, Brain, ShieldAlert, Wallet, List, Bitcoin, Download, Upload, Key, Database } from 'lucide-react';


// ==========================================
// 🧬 COMPONENTE: DOJO (PROTOCOLO APOCALIPSE)
// ==========================================
function DojoPanel({ state }) {
  const [senha, setSenha] = useState('');
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mensagem, setMensagem] = useState('');

  // Converte a URL do WebSocket para a URL da API HTTP (Render)
  const wsUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000/ws";
  const API_URL = wsUrl.replace('wss://', 'https://').replace('ws://', 'http://').replace('/ws', '');

  const handleDownload = () => {
    if (!senha) { setMensagem('⚠️ Digite a senha Admin primeiro.'); return; }
    window.open(`${API_URL}/download-dados?senha=${senha}`, '_blank');
    setMensagem('📥 Solicitando download do histórico...');
  };

  const handleUpload = async () => {
    if (!senha) { setMensagem('⚠️ Digite a senha Admin.'); return; }
    if (!file) { setMensagem('⚠️ Selecione o arquivo .zip do Novo Cérebro.'); return; }

    setLoading(true);
    setMensagem('🚀 Injetando nova Geração na Matrix...');
    
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API_URL}/upload-cerebro?senha=${senha}`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      
      if (res.ok) {
        setMensagem(`✅ ${data.mensagem}`);
        setFile(null);
      } else {
        setMensagem(`❌ Erro: ${data.detail}`);
      }
    } catch (err) {
      setMensagem('❌ Erro de conexão com o servidor da Nuvem.');
    }
    setLoading(false);
  };

  return (
    <div className="bg-slate-800/50 p-6 rounded-xl border border-purple-500/30 shadow-lg shadow-purple-900/20 mt-6">
      <h2 className="text-xl font-bold text-purple-400 mb-4 flex items-center gap-2 border-b border-purple-900/50 pb-3">
        <Brain size={24} /> Laboratório Neural (Dojo)
      </h2>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* COLUNA 1: AUTENTICAÇÃO */}
        <div className="space-y-3 bg-slate-900/50 p-4 rounded-lg border border-slate-700">
          <label className="text-xs font-semibold text-slate-400 uppercase flex items-center gap-2">
            <Key size={14} className="text-yellow-500"/> Chave de Autorização
          </label>
          <input 
            type="password" 
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded p-2 text-white focus:outline-none focus:border-purple-500 transition-colors font-mono text-sm"
            placeholder="••••••••"
          />
          {mensagem && (
            <div className={`p-2 rounded text-xs font-mono text-center border ${mensagem.includes('✅') ? 'bg-green-900/30 border-green-500 text-green-400' : 'bg-red-900/30 border-red-500 text-red-400'}`}>
              {mensagem}
            </div>
          )}
        </div>

        {/* COLUNA 2: EXTRAÇÃO (DOWNLOAD) */}
        <div className="space-y-3 bg-slate-900/50 p-4 rounded-lg border border-slate-700 flex flex-col justify-between">
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase flex items-center gap-2 mb-2">
              <Database size={14} className="text-blue-500"/> Coleta de Dados
            </label>
            <p className="text-xs text-slate-500 mb-2">
              Baixe o histórico do mercado para treinar a IA no seu PC local. 
              Tempo recomendado: <strong className="text-yellow-400">24h+</strong>
            </p>
          </div>
          <button 
            onClick={handleDownload}
            className="w-full bg-blue-600/20 hover:bg-blue-600/40 text-blue-400 border border-blue-500/50 font-semibold py-2 px-4 rounded transition-all flex justify-center items-center gap-2 text-sm"
          >
            <Download size={16}/> Exportar Conhecimento (CSV)
          </button>
        </div>

        {/* COLUNA 3: INJEÇÃO (UPLOAD) */}
        <div className="space-y-3 bg-slate-900/50 p-4 rounded-lg border border-slate-700 flex flex-col justify-between">
          <div>
            <label className="text-xs font-semibold text-slate-400 uppercase flex items-center gap-2 mb-2">
              <Upload size={14} className="text-purple-500"/> Atualização Neural
            </label>
            <input 
              type="file" 
              accept=".zip"
              onChange={(e) => setFile(e.target.files ? e.target.files[0] : null)}
              className="block w-full text-xs text-slate-400 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-purple-600/20 file:text-purple-400 hover:file:bg-purple-600/40 cursor-pointer mb-2"
            />
          </div>
          <button 
            onClick={handleUpload}
            disabled={loading || !file}
            className={`w-full font-bold py-2 px-4 rounded transition-all flex justify-center items-center gap-2 text-sm ${
              loading || !file 
              ? 'bg-slate-700 text-slate-500 cursor-not-allowed border border-slate-600' 
              : 'bg-purple-600 hover:bg-purple-500 text-white shadow-lg shadow-purple-500/30'
            }`}
          >
            <Zap size={16}/> {loading ? 'Injetando...' : 'Aplicar Geração'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ==========================================
// 📊 DASHBOARD PRINCIPAL
// ==========================================
export default function Dashboard() {
  const [data, setData] = useState(null);
  const chartContainerRef = useRef(null);
  const chartInstance = useRef(null);
  const seriesInstance = useRef(null);
  const tradeSeriesInstance = useRef(null);
  const markersPluginInstance = useRef(null); 
  const ws = useRef(null);

  const priceLineRef = useRef(null);

  // 🛑 A TRAVA MÁGICA CONTRA O RESET DO ZOOM
  const isDataLoaded = useRef(false); 

  useEffect(() => {
    const socketUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000/ws";
    ws.current = new WebSocket(socketUrl);
    
    ws.current.onmessage = (event) => {
      const message = JSON.parse(event.data);
      setData(message);

      if (seriesInstance.current && chartInstance.current) {
        
        // --- 🛡️ GESTÃO DA LINHA DE ENTRADA ATUAL ---
        if (message.in_position && message.entry_price) {
          if (!priceLineRef.current) {
            priceLineRef.current = seriesInstance.current.createPriceLine({
              price: message.entry_price,
              color: message.current_position === 1 ? '#22c55e' : '#ef4444',
              lineWidth: 2,
              lineStyle: 2,
              axisLabelVisible: true,
              title: 'ENTRADA',
            });
          }
        } else {
          if (priceLineRef.current) {
            seriesInstance.current.removePriceLine(priceLineRef.current);
            priceLineRef.current = null;
          }
        }
        // -----------------------------------------------

        // 1. CARGA INICIAL
        if (!isDataLoaded.current && message.chart_data?.length > 0) {
          const sorted = [...message.chart_data].sort((a, b) => a.time - b.time);
          const unique = sorted.filter((v, i, a) => a.findIndex(t => (t.time === v.time)) === i);
          seriesInstance.current.setData(unique);
          
          // Injeta o histórico de rastros (Efeito IQ Option)
          if (message.trade_lines && message.trade_lines.length > 0 && tradeSeriesInstance.current) {
            tradeSeriesInstance.current.setData(message.trade_lines);
          }
          
          chartInstance.current.timeScale().fitContent();
          isDataLoaded.current = true;
        } 
        // 2. PING DE PREÇO REAL
        else if (isDataLoaded.current && message.last_candle?.time) {
          try {
            seriesInstance.current.update(message.last_candle);
            
            // ATUALIZAÇÃO DO VETOR: Substitui a linha inteira para não bugar o desenho
            if (message.trade_lines && tradeSeriesInstance.current) {
              tradeSeriesInstance.current.setData(message.trade_lines); // 👈 Usa setData ao invés de update
            }
          } catch (e) {}
        }
        
        // 3. SETAS DE OPERAÇÃO
        if (message.markers?.length > 0 && markersPluginInstance.current) {
          try {
            const sortedMarkers = [...message.markers].sort((a, b) => a.time - b.time);
            markersPluginInstance.current.setMarkers(sortedMarkers);
          } catch (e) {}
        }
      }
    };
    
    return () => { if (ws.current) ws.current.close(); };
  }, []);

  useEffect(() => {
    if (!chartContainerRef.current || !data || data.chart_data.length === 0) return;
    if (chartInstance.current) return; // IMPEDE O REACT DE DESTRUIR O GRÁFICO

    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      timeScale: { 
        timeVisible: true, 
        secondsVisible: false,
        borderColor: '#334155',
        shiftVisibleRangeOnNewBar: false, // 🛑 DESLIGA O "ÍMÃ" DO TRADINGVIEW
      },
      rightPriceScale: { borderColor: '#334155' },
    });

    const newSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444', borderUpColor: '#22c55e', borderDownColor: '#ef4444', wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });

   // 👇 NOVA SÉRIE: O Rastro Histórico da IQ Option 👇
    const tradeSeries = chart.addSeries(LineSeries, {
      color: '#3b82f6', // Azul elétrico
      lineWidth: 2,
      lineStyle: 2, // Tracejado
      crosshairMarkerVisible: false,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    tradeSeriesInstance.current = tradeSeries;

    const markersPlugin = createSeriesMarkers(newSeries, []);
    markersPluginInstance.current = markersPlugin;
    
    // Liga as instâncias à memória
    chartInstance.current = chart;
    seriesInstance.current = newSeries;

    // Se no momento de criar o quadro os dados já estiverem ali, injetamos:
    if (!isDataLoaded.current && data.chart_data && data.chart_data.length > 0) {
        const sorted = [...data.chart_data].sort((a, b) => a.time - b.time);
        const unique = sorted.filter((v, i, a) => a.findIndex(t => (t.time === v.time)) === i);
        newSeries.setData(unique);
        
        if (data.trade_lines && data.trade_lines.length > 0) {
            tradeSeries.setData(data.trade_lines);
        }
        
        if (data.markers && data.markers.length > 0) {
            const sortedMarkers = [...data.markers].sort((a, b) => a.time - b.time);
            markersPlugin.setMarkers(sortedMarkers);
        }
        chart.timeScale().fitContent();
        isDataLoaded.current = true;
    }

    const handleResize = () => chart.applyOptions({ width: chartContainerRef.current.clientWidth });
    window.addEventListener('resize', handleResize);
    
    return () => { 
      window.removeEventListener('resize', handleResize); 
      chart.remove(); 
      chartInstance.current = null; 
      seriesInstance.current = null;
      tradeSeriesInstance.current = null;
      markersPluginInstance.current = null;
      isDataLoaded.current = false;
    };
  }, [data !== null]); 

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
                Win Rate: {data.adaptation.current_win_rate}% 
                <span className="text-slate-400 ml-2">
                  ({data.adaptation.wins || 0}W / {data.adaptation.losses || 0}L)
                </span>
              </div>
            </div>
            <div className="text-xs text-purple-400/70 mt-2 z-10 relative font-mono uppercase tracking-wider">
              Status: {data.adaptation.learning_state}
            </div>
         </div>
      </div>

      {/* ÁREA PRINCIPAL: GRÁFICO E LIVRO DE OFERTAS */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-3 bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 shadow-lg flex flex-col">
           <div ref={chartContainerRef} className="w-full relative rounded overflow-hidden" style={{ height: '450px' }}></div>
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

      {/* NOVO: PAINEL DE CONTROLE HÍBRIDO */}
      <DojoPanel state={data} />

    </div>
  );
}