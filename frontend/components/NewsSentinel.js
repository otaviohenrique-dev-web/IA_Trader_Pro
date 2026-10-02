import React from "react";
import { ShieldCheck, ShieldAlert, ShieldX, Newspaper, Radio } from "lucide-react";
import { Gemini } from "@lobehub/icons";

const TONES = {
  SAFE: { label: "Seguro", text: "text-gain", ring: "border-gain/30", chip: "bg-gain/10", Icon: ShieldCheck },
  CAUTION: { label: "Atenção", text: "text-warn", ring: "border-warn/30", chip: "bg-warn/10", Icon: ShieldAlert },
  DANGER: { label: "Perigo", text: "text-loss", ring: "border-loss/40", chip: "bg-loss/10", Icon: ShieldX },
  "MODO TÉCNICO": { label: "Modo técnico", text: "text-slate-300", ring: "border-slate-500/30", chip: "bg-slate-500/10", Icon: ShieldCheck },
  BAIXO: { label: "Baixo", text: "text-gain", ring: "border-gain/30", chip: "bg-gain/10", Icon: ShieldCheck },
  "INICIALIZANDO...": { label: "Iniciando", text: "text-accent", ring: "border-accent/30", chip: "bg-accent/10", Icon: Newspaper },
};

const IMPACT = {
  SAFE: "Modo observação: mostra o contexto, sem interferir no robô.",
  CAUTION: "Atenção registrada. Em observação: não bloqueia entradas (medindo se ajuda).",
  DANGER: "Risco alto registrado. Em observação: não bloqueia entradas (medindo se ajuda).",
  "MODO TÉCNICO": "Sem acesso a notícias: operando só com análise técnica.",
};

export default function NewsSentinel({ data }) {
  if (!data) return null;
  const { status, last_headlines, reason } = data;
  const tone = TONES[status] || TONES[data.risk_level] || TONES.SAFE;
  const Icon = tone.Icon;
  const scorePct = Math.max(0, Math.min(100, Math.round((data.sentiment_score || 0) * 100)));
  const bar = scorePct > 80 ? "bg-loss" : scorePct > 60 ? "bg-warn" : "bg-gain";
  const scoreText = scorePct > 80 ? "text-loss" : scorePct > 60 ? "text-warn" : "text-gain";

  return (
    <section className={`card flex flex-col overflow-hidden p-5 ${tone.ring} transition-colors duration-500`}>
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg border border-line bg-white/5">
            <Gemini.Color size={18} />
          </span>
          <div>
            <h3 className="text-sm font-bold leading-tight text-white">Analista de Notícias</h3>
            <p className="text-[10px] text-slate-500">Leitura de risco macro por IA · <span className="font-semibold text-violet">modo observação</span></p>
          </div>
        </div>
        <span className={`flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-bold ${tone.ring} ${tone.chip} ${tone.text}`}>
          <Icon size={12} /> {tone.label}
        </span>
      </header>

      <div className="mt-5">
        <div className="flex items-end justify-between">
          <span className="eyebrow">Índice de risco</span>
          <span className={`num text-3xl font-black leading-none ${scoreText}`}>{scorePct}<span className="text-base">%</span></span>
        </div>
        <div className="relative mt-2.5 h-2 w-full overflow-hidden rounded-full bg-white/5">
          <div className={`h-full rounded-full transition-all duration-1000 ${bar}`} style={{ width: `${scorePct}%` }} />
          <span className="absolute inset-y-0 left-[60%] w-px bg-white/25" />
          <span className="absolute inset-y-0 left-[80%] w-px bg-white/25" />
        </div>
        <div className="mt-1 flex text-[9px] font-semibold uppercase tracking-wider text-slate-500">
          <span className="w-[60%]">Seguro</span><span className="w-[20%]">Atenção</span><span className="w-[20%] text-right">Perigo</span>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-line bg-black/20 p-3">
        <p className="text-xs italic leading-relaxed text-slate-300">
          {reason ? `“${reason}”` : "Aguardando a primeira leitura do mercado…"}
        </p>
        <p className={`mt-2 border-t border-line pt-2 text-[11px] font-medium ${tone.text}`}>
          {IMPACT[status] || IMPACT.SAFE}
        </p>
      </div>

      <div className="group relative mt-4 flex h-11 items-center overflow-hidden rounded-xl border border-line bg-black/30">
        <span className="absolute left-0 z-20 flex h-full items-center gap-1 bg-panel px-2.5 text-[10px] font-bold uppercase tracking-wider text-warn">
          <Radio size={11} className="animate-pulse" /> Ao vivo
        </span>
        <div className="pointer-events-none absolute inset-y-0 left-[84px] z-10 w-8 bg-linear-to-r from-panel to-transparent" />
        <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-8 bg-linear-to-l from-panel to-transparent" />
        <div className="news-track ml-[84px] whitespace-nowrap">
          {last_headlines?.length ? (
            [...last_headlines, ...last_headlines].map((n, i) => (
              <span key={i} className="mx-5 text-[11px] text-slate-300">{n}</span>
            ))
          ) : (
            <span className="mx-5 text-[11px] text-slate-600">Aguardando novas manchetes…</span>
          )}
        </div>
      </div>

      <style jsx>{`
        @keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        .news-track { display: inline-flex; animation: marquee 180s linear infinite; }
        .group:hover .news-track { animation-play-state: paused; }
        @media (prefers-reduced-motion: reduce) { .news-track { animation: none; } }
      `}</style>
    </section>
  );
}
