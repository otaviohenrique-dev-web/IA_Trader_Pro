"use client";

import React, { useState, useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts'; 
import { Activity, CircleDot, Clock, Zap, Brain, ShieldAlert, Wallet, List, Bitcoin, Download, Upload, Key, Database } from 'lucide-react';

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
  return pivots;
};

// ==========================================
// 🧬 COMPONENTE: DOJO (PROTOCOLO APOCALIPSE)
// ==========================================
function DojoPanel({ state }) {
  const [senha, setSenha] = useState('');
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mensagem, setMensagem] = useState('');

  const wsUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:10000/ws";
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
// 📈 COMPONENTE DE GRÁFICO ISOLADO (AUDITORIA LIMPA)
// ==========================================
function TradingChart({ liveCandle, markersData }) {
    const chartContainerRef = useRef(null);
    const tooltipRef = useRef(null);
    const chartInstance = useRef(null);
    const seriesInstance = useRef(null);
    const zigzagSeriesRef = useRef(null);
    const exactTradeLineRef = useRef(null);
    const isDataLoaded = useRef(false);
    
    // 🧠 Memória interna para guardar referências rápidas dos marcadores e preços
    const markersRef = useRef([]);
    const chartDataMap = useRef(new Map());

    // Atualiza a memória de marcadores sempre que chegam via props
    useEffect(() => {
        if (markersData) {
            markersRef.current = markersData;
        }
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

        // 🎯 CANDLE DIMMING: Configuração Padrão Cinza Escuro
        const newSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#1e293b', 
            downColor: '#1e293b', 
            borderUpColor: '#334155', 
            borderDownColor: '#334155', 
            wickUpColor: '#334155', 
            wickDownColor: '#334155',
        });

        // 🎯 ESTRUTURA MACRO: ZigZag Azul Celeste Fino
        const zigzagSeries = chart.addSeries(LineSeries, {
            color: '#38bdf8', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
        });

        // 🎯 AUDITORIA: Vetor de Precisão Sob Demanda (Invisível por Padrão)
        const exactTradeLine = chart.addSeries(LineSeries, {
            color: '#a855f7', lineWidth: 2, lineStyle: 3, crosshairMarkerVisible: true, lastValueVisible: false, priceLineVisible: false,
        });

        chartInstance.current = chart;
        seriesInstance.current = newSeries;
        zigzagSeriesRef.current = zigzagSeries;
        exactTradeLineRef.current = exactTradeLine;

        const carregarHistorico = async () => {
            const API_URL = "http://127.0.0.1:10000"; 
            try {
                const res = await fetch(`${API_URL}/api/historico`);
                if (res.ok) {
                    const data = await res.json();
                    if (data && data.length > 0) {
                        const unique = [...data].sort((a, b) => a.time - b.time);
                        
                        // 1. Guarda os preços num Mapa para uso da Linha Exata depois
                        unique.forEach(candle => {
                            chartDataMap.current.set(candle.time, candle);
                        });

                        // 2. Aplica as Cores Neon apenas nas velas com Markers
                        const dimmedData = unique.map(candle => {
                            const marker = markersRef.current.find(m => m.time === candle.time);
                            if (marker) {
                                return { ...candle, color: marker.color, wickColor: marker.color, borderColor: marker.color };
                            }
                            return candle; // Mantém cinza
                        });

                        newSeries.setData(dimmedData);
                        
                        const zData = calculateZigZag(dimmedData, 0.8);
                        zigzagSeries.setData(zData);

                        chart.timeScale().fitContent();
                        isDataLoaded.current = true;
                    }
                }
            } catch (err) { console.error("Erro ao buscar dados iniciais.", err); }
        };

        carregarHistorico();

        // 🎯 MOTOR DE RAIO-X INTERATIVO (HOVER)
        chart.subscribeCrosshairMove((param) => {
            const tooltip = tooltipRef.current;
            if (!param.time || param.point.x < 0 || param.point.y < 0 || !tooltip) {
                tooltip.style.display = 'none';
                exactTradeLine.setData([]); // Esconde a linha
                return;
            }

            const hoveredMarker = markersRef.current.find(m => m.time === param.time);
            const candleData = chartDataMap.current.get(param.time) || param.seriesData.get(newSeries);

            if (hoveredMarker && candleData) {
                tooltip.style.display = 'block';
                tooltip.style.left = param.point.x + 15 + 'px';
                tooltip.style.top = param.point.y + 15 + 'px';
                
                // Semântica Visual
                const isEntry = hoveredMarker.shape === 'circle';
                const direction = hoveredMarker.text.includes('LONG') ? '⬆️ LONG' : '⬇️ SHORT';
                const result = hoveredMarker.text === 'WIN' ? '✅ WIN' : (hoveredMarker.text === 'LOSS' ? '❌ LOSS' : '');
                
                // Extração da Fotografia Mental (se os dados foram enviados na api/websocket)
                const rsiText = candleData.rsi ? candleData.rsi.toFixed(2) : 'Aguardando...';
                const bbText = candleData.bb_width ? candleData.bb_width.toFixed(2) : 'Aguardando...';

                tooltip.innerHTML = `
                    <div class="font-bold text-sm mb-1 ${hoveredMarker.color === '#22c55e' ? 'text-green-400' : 'text-red-400'}">
                        ${isEntry ? 'ESTADO IA: ENTRADA' : 'ESTADO IA: SAÍDA'}
                    </div>
                    <div class="text-xs text-white mb-1">Ação: ${isEntry ? direction : result}</div>
                    <div class="text-xs text-slate-300">Preço: $${candleData.close.toFixed(2)}</div>
                    <div class="mt-2 pt-2 border-t border-slate-600 text-[10px] text-slate-400 font-mono">
                        RSI: ${rsiText}<br/>
                        BB Largura: ${bbText}
                    </div>
                `;

                // 🎯 Desenhar Vetor de Precisão (A -> B)
                if (isEntry) {
                    // Busca o próximo marcador de saída
                    const exitMarker = markersRef.current.find(m => m.time > param.time && m.shape === 'square');
                    if (exitMarker) {
                        const exitCandle = chartDataMap.current.get(exitMarker.time);
                        exactTradeLine.setData([
                            { time: param.time, value: candleData.close },
                            { time: exitMarker.time, value: exitCandle ? exitCandle.close : candleData.close }
                        ]);
                    }
                } else {
                    // Se estiver no hover da Saída, busca o marcador de entrada correspondente
                    const entryMarker = [...markersRef.current].reverse().find(m => m.time < param.time && m.shape === 'circle');
                    if (entryMarker) {
                        const entryCandle = chartDataMap.current.get(entryMarker.time);
                        exactTradeLine.setData([
                            { time: entryMarker.time, value: entryCandle ? entryCandle.close : candleData.close },
                            { time: param.time, value: candleData.close }
                        ]);
                    }
                }
            } else {
                tooltip.style.display = 'none';
                exactTradeLine.setData([]); // Apaga o vetor se sair do candle colorido
            }
        });

        const resizeObserver = new ResizeObserver(entries => {
            if (entries.length === 0 || !chartInstance.current) return;
            const { width, height } = entries[0].contentRect;
            chartInstance.current.applyOptions({ width, height });
        });
        resizeObserver.observe(chartContainerRef.current);

        return () => {
            resizeObserver.disconnect();
            chart.remove();
            chartInstance.current = null;
        };
    }, []); 

    // Efeito Reativo: Atualiza a vela ao vivo e pinta de Neon se houver sinal
    useEffect(() => {
        if (isDataLoaded.current && seriesInstance.current && liveCandle?.time) {
            chartDataMap.current.set(liveCandle.time, liveCandle); // Atualiza memória

            let cColor = '#1e293b'; // Default dimming
            const hasAction = markersRef.current.find(m => m.time === liveCandle.time);
            if (hasAction) cColor = hasAction.color; // Aplica o Neon

            try {
                seriesInstance.current.update({
                    ...liveCandle,
                    color: cColor, wickColor: cColor, borderColor: cColor
                });
            } catch (e) {}
        }
    }, [liveCandle]);

    // Efeito Reativo: Atualiza as Setas sem recarregar o gráfico
    useEffect(() => {
        if (isDataLoaded.current && seriesInstance.current && markersData?.length > 0) {
            try {
                const sortedMarkers = [...markersData].sort((a, b) => a.time - b.time);
                seriesInstance.current.setMarkers(sortedMarkers);
            } catch (e) {}
        }
    }, [markersData]);

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
// 📊 DASHBOARD PRINCIPAL (O Pai)
// ==========================================
export default function Dashboard() {
  const [data, setData] = useState(null);
  const ws = useRef(null);

  useEffect(() => {
    const socketUrl = process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:10000/ws";
    ws.current = new WebSocket(socketUrl);
    
    ws.current.onmessage = (event) => {
      const message = JSON.parse(event.data);
      setData(message);
    };
    
    return () => { if (ws.current) ws.current.close(); };
  }, []);

  if (!data) return (
    <div className="min-h-screen bg-[#0f172a] flex flex-col items-center justify-center text-white font-mono">
      <Activity className="animate-spin mb-4 text-purple-500" size={48} /> 
      <p>Sincronizando com a Matrix...</p>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#0f172a] p-6 font-sans text-slate-100 relative">
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

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-3 bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 shadow-lg flex flex-col">
           {/* 🚀 O COMPONENTE DE GRÁFICO ISOLADO COM A AUDITORIA LIMPA ATIVADA! */}
           <TradingChart liveCandle={data.last_candle} markersData={data.markers} />
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

      <DojoPanel state={data} />
    </div>
  );
}