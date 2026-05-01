import React from 'react';
import { ShieldCheck, ShieldAlert, ShieldX, Newspaper, Radio } from 'lucide-react';
import { Gemini } from '@lobehub/icons'; // Novo Ícone Premium

export default function NewsSentinel({ data }) {
  if (!data) return null;

  // Adicionamos a extração da variável 'reason' enviada pelo backend
  const { status, sentiment_score, risk_level, last_headlines, reason } = data;

  const config = {
    SAFE: { color: 'text-green-400', border: 'border-green-500/30', bg: 'bg-green-500/10', icon: <ShieldCheck size={18}/> },
    CAUTION: { color: 'text-yellow-400', border: 'border-yellow-500/30', bg: 'bg-yellow-500/10', icon: <ShieldAlert size={18}/> },
    DANGER: { color: 'text-red-400', border: 'border-red-500/30', bg: 'bg-red-500/10', icon: <ShieldX size={18}/> },
    'MODO TÉCNICO': { color: 'text-slate-300', border: 'border-slate-500/30', bg: 'bg-slate-500/10', icon: <ShieldCheck size={18}/> },
    BAIXO: { color: 'text-green-400', border: 'border-green-500/30', bg: 'bg-green-500/10', icon: <ShieldCheck size={18}/> },
    'INICIALIZANDO...': { color: 'text-blue-400', border: 'border-blue-500/30', bg: 'bg-blue-500/10', icon: <Newspaper size={18}/> },
  };

  const rotuloStatus = {
    SAFE: 'Seguro',
    CAUTION: 'Atenção',
    DANGER: 'Perigo',
    'MODO TÉCNICO': 'Modo técnico',
    BAIXO: 'Baixo',
    'INICIALIZANDO...': 'Inicializando',
  };

  const current = config[risk_level] || config[status] || config.SAFE;

  const score = data?.sentiment_score || 0;
  const scorePct = Math.round(score * 100);

  // NOVO: Cores alinhadas com a calibragem de 60% (SAFE) e 80% (CAUTION) do backend
  let barColorClass = "bg-green-500"; 
  let textColorClass = "text-green-400";

  if (scorePct > 60 && scorePct <= 80) {
    barColorClass = "bg-yellow-500"; 
    textColorClass = "text-yellow-400";
  } else if (scorePct > 80) {
    barColorClass = "bg-red-500 animate-pulse"; 
    textColorClass = "text-red-400";
  }

  return (
    <div className={`h-full p-4 rounded-xl border ${current.border} ${current.bg} backdrop-blur-sm flex flex-col justify-between overflow-hidden shadow-lg transition-all duration-500`}>
      
      {/* 1. Header do Analista (Premium) */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {/* Note que reduzi o size de 56 para 20 para não estourar o layout da header, mantendo a elegância */}
          <Gemini.Color size={20} type={'color'}/>
          <h3 className="font-bold text-white text-[11px] uppercase tracking-tighter italic">Analista de Notícias</h3>
        </div>
        <div className={`px-2 py-0.5 rounded text-[9px] font-black border ${current.border} ${current.color} bg-black/40 font-mono`}>
          {rotuloStatus[status] || status}
        </div>
      </div>

      <div className="mt-auto">
        <div className="flex justify-between items-end mb-1">
          <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">
            Sentimento macro
          </span>
          <span className={`text-xl font-black font-mono ${textColorClass}`}>
            {scorePct}%
          </span>
        </div>
        
        {/* O fundo da barra (Trilho) */}
        <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-1000 ease-in-out ${barColorClass}`} 
            style={{ width: `${scorePct}%` }} 
          />
        </div>
      </div> 

      {/* 2. Parecer Textual da IA (Injetado do Backend) */}
      <div className="mt-3 mb-3 p-2 bg-black/40 border border-slate-700/50 rounded-lg min-h-10 flex items-center">
        <p className="text-[10px] text-slate-300 font-mono italic leading-relaxed">
          <span className="text-blue-400 font-bold not-italic">Parecer: </span>
          {reason ? `"${reason}"` : "Aguardando sincronização neural..."}
        </p>
      </div>

      {/* 3. O LETREIRO DE LED (Ticker) */}
      <div className="relative bg-black/60 border border-orange-500/20 rounded p-2 h-16 flex items-center overflow-hidden group shadow-inner mt-auto">
        <div className="absolute left-0 top-0 bottom-0 w-10 bg-linear-to-r from-black/80 to-transparent z-10 pointer-events-none" />
        <div className="absolute right-0 top-0 bottom-0 w-10 bg-linear-to-l from-black/80 to-transparent z-10 pointer-events-none" />
        
        <div className="flex whitespace-nowrap animate-marquee group-hover:pause transition-all duration-300">
          {last_headlines && last_headlines.length > 0 ? (
            [...last_headlines, ...last_headlines].map((news, i) => (
              <span key={i} className="text-[11px] font-mono text-orange-400/90 mx-6 flex items-center gap-2 tracking-wide">
                <Radio size={10} className="text-orange-600 animate-pulse" /> {news}
              </span>
            ))
          ) : (
            <span className="text-[11px] font-mono text-gray-600 uppercase mx-4">
              Aguardando novo fluxo de frequências...
            </span>
          )}
        </div>
      </div>

      {/* Estilo Global para a Animação */}
      <style jsx>{`
        @keyframes marquee {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .animate-marquee {
          display: inline-flex;
          animation: marquee 180s linear infinite; 
        }
        .group:hover .animate-marquee {
          animation-play-state: paused;
        }
      `}</style>
    </div>
  );
}