import React from "react";
import { Crosshair, TrendingUp, ShieldOff, Hourglass, Eye } from "lucide-react";
import { fmtPrice, fmtPct } from "../lib/format";

const STATUS = {
  oportunidade: { label: "Oportunidade", text: "text-gain", ring: "border-gain/50", Icon: Crosshair },
  "em posição": { label: "Comprado", text: "text-accent", ring: "border-accent/50", Icon: TrendingUp },
  "em cooldown": { label: "Cooldown", text: "text-violet", ring: "border-violet/30", Icon: Hourglass },
  "regime de baixa": { label: "Regime de baixa", text: "text-loss", ring: "border-loss/30", Icon: ShieldOff },
  "sem oportunidade": { label: "Observando", text: "text-slate-400", ring: "border-line", Icon: Eye },
  aguardando: { label: "Aguardando", text: "text-slate-500", ring: "border-line", Icon: Hourglass },
};

// escala do medidor de EV: de -0,3 R a +0,5 R; a marca branca é o limiar de entrada do modelo
const MIN = -0.3, MAX = 0.5;
const pos = (v) => Math.max(0, Math.min(100, ((v - MIN) / (MAX - MIN)) * 100));

function Card({ asset, d, thr, selected, onSelect }) {
  const st = STATUS[d.status] || STATUS.aguardando;
  const Icon = st.Icon;
  const hasEv = d.ev != null;
  const pnl = d.position && d.price ? ((d.price - d.position.entry) / d.position.entry) * 100 : null;
  return (
    <button type="button" onClick={() => onSelect(asset)}
      className={`card relative w-full p-4 text-left transition-all hover:-translate-y-0.5 ${st.ring} ${selected ? "ring-1 ring-accent/60" : ""}`}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm font-black text-white">
          {asset}<span className="text-[10px] font-medium text-slate-500">/USDT</span>
        </span>
        <span className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold ${st.ring} ${st.text}`}>
          <Icon size={11} /> {st.label}
        </span>
      </div>

      <div className="num mt-3 text-xl font-black leading-none text-white">{d.price ? `$${fmtPrice(d.price)}` : "—"}</div>

      <div className="mt-4">
        <div className="mb-1.5 flex items-center justify-between text-[11px]">
          <span className="font-medium text-slate-400">Ganho esperado</span>
          <span className={`num font-bold ${!hasEv ? "text-slate-500" : d.ev >= thr ? "text-gain" : d.ev > 0 ? "text-slate-200" : "text-loss"}`}>
            {hasEv ? `${d.ev >= 0 ? "+" : ""}${d.ev.toFixed(2)} R` : "—"}
          </span>
        </div>
        <div className="relative h-1.5 overflow-hidden rounded-full bg-white/5">
          {hasEv && <div className={`absolute inset-y-0 left-0 rounded-full transition-all duration-700 ${d.ev >= thr ? "bg-gain" : "bg-slate-500"}`} style={{ width: `${pos(d.ev)}%` }} />}
          {thr != null && <span className="absolute inset-y-0 w-0.5 bg-white/80" style={{ left: `${pos(thr)}%` }} />}
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-slate-500">
          <span>entra acima de +{thr != null ? thr.toFixed(2) : "—"} R</span>
          {d.stop_pct != null && <span>stop {fmtPct(d.stop_pct * 100, 1).replace("+", "")}</span>}
        </div>
      </div>

      {pnl != null && (
        <div className={`num mt-3 rounded-lg border px-2 py-1 text-center text-[11px] font-bold ${pnl >= 0 ? "border-gain/30 bg-gain/10 text-gain" : "border-loss/30 bg-loss/10 text-loss"}`}>
          posição aberta {fmtPct(pnl)}
        </div>
      )}
    </button>
  );
}

export default function AssetRadar({ portfolio, selected, onSelect }) {
  const assets = portfolio?.assets || {};
  const names = Object.keys(assets);
  if (!names.length) return null;
  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold text-white"><Crosshair size={15} className="text-accent" /> Radar de oportunidades</h2>
        <span className="text-[11px] text-slate-500">toque em um par para ver o gráfico</span>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 [&>*]:min-w-0">
        {names.map((a) => <Card key={a} asset={a} d={assets[a]} thr={portfolio.thr} selected={selected === a} onSelect={onSelect} />)}
      </div>
    </section>
  );
}
