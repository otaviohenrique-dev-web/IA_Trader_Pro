import React from 'react';
import { ShieldCheck, ShieldAlert, ShieldX, Newspaper, Radio } from 'lucide-react';

export default function NewsSentinel({ data }) {
  if (!data) return null;

  const { status, sentiment_score, risk_level, last_headlines } = data;

  const config = {
    SAFE: { color: 'text-green-400', border: 'border-green-500/30', bg: 'bg-green-500/10', icon: <ShieldCheck size={18}/> },
    CAUTION: { color: 'text-yellow-400', border: 'border-yellow-500/30', bg: 'bg-yellow-500/10', icon: <ShieldAlert size={18}/> },
    DANGER: { color: 'text-red-400', border: 'border-red-500/30', bg: 'bg-red-500/10', icon: <ShieldX size={18}/> },
  };

  const current = config[risk_level] || config.SAFE;

// Garante que o score é um número válido e converte para %
  const score = data?.sentiment_score || 0;
  const scorePct = Math.round(score * 100);

  // Define a cor da barra baseada no nível de risco configurado no backend
  let barColorClass = "bg-green-500"; // SAFE (0% - 45%)
  let textColorClass = "text-green-400";

  if (scorePct > 45 && scorePct <= 75) {
    barColorClass = "bg-yellow-500"; // CAUTION (46% - 75%)
    textColorClass = "text-yellow-400";
  } else if (scorePct > 75) {
    barColorClass = "bg-red-500 animate-pulse"; // DANGER (76% - 100%)
    textColorClass = "text-red-400";
  }


  return (
    <div className={`h-full p-4 rounded-xl border ${current.border} ${current.bg} backdrop-blur-sm flex flex-col justify-between overflow-hidden shadow-lg transition-all duration-500`}>
      
      {/* 1. Header do Analista */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`${current.color} animate-pulse`}>{current.icon}</div>
          <h3 className="font-bold text-white text-[11px] uppercase tracking-tighter italic">Analista do BTC</h3>
        </div>
        <div className={`px-2 py-0.5 rounded text-[9px] font-black border ${current.border} ${current.color} bg-black/40 font-mono`}>
          {status}
        </div>
      </div>

      <div className="mt-auto">
        <div className="flex justify-between items-end mb-1">
          <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">
            Sentimento Macro
          </span>
          {/* O texto da porcentagem muda de cor junto com a barra */}
          <span className={`text-xl font-black font-mono ${textColorClass}`}>
            {scorePct}%
          </span>
        </div>
        
        {/* O fundo da barra (Trilho) */}
        <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
          {/* A barra de progresso que enche e muda de cor dinamicamente */}
          <div 
            className={`h-full transition-all duration-1000 ease-in-out ${barColorClass}`} 
            style={{ width: `${scorePct}%` }} 
          />
        </div>
      </div> <br />
      {/* 3. O LETREIRO DE LED (Ticker) */}
      <div className="relative bg-black/60 border border-orange-500/20 rounded p-2 h-16 flex items-center overflow-hidden group shadow-inner">
        {/* Efeito de Gradiente nas bordas para suavizar o sumiço do texto */}
        <div className="absolute left-0 top-0 bottom-0 w-10 bg-gradient-to-r from-black/80 to-transparent z-10 pointer-events-none" />
        <div className="absolute right-0 top-0 bottom-0 w-10 bg-gradient-to-l from-black/80 to-transparent z-10 pointer-events-none" />
        
        <div className="flex whitespace-nowrap animate-marquee group-hover:pause transition-all duration-300">
          {last_headlines && last_headlines.length > 0 ? (
            // Duplicamos a lista para o loop ser contínuo e sem pulos
            [...last_headlines, ...last_headlines].map((news, i) => (
              <span key={i} className="text-[11px] font-mono text-orange-400/90 mx-6 uppercase flex items-center gap-2 tracking-wide">
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
          /* 120s = Velocidade de leitura confortável para 10 notícias */
          /* 180s = Velocidade bem lenta, estilo terminal de banco */
          animation: marquee 180s linear infinite; 
        }
        .group:hover .animate-marquee {
          animation-play-state: paused;
        }
      `}</style>
    </div>
  );
}