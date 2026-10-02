import React from "react";
import { Cpu, ShieldCheck, Timer, Layers, Target } from "lucide-react";

function Meter({ label, value, max, text, tone = "bg-accent", mark }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-[11px]">
        <span className="font-medium text-slate-400">{label}</span>
        <span className="num font-semibold text-slate-200">{text}</span>
      </div>
      <div className="relative h-1.5 overflow-hidden rounded-full bg-white/5">
        <div className={`h-full rounded-full transition-all duration-700 ${tone}`} style={{ width: `${pct}%` }} />
        {mark != null && <span className="absolute inset-y-0 w-0.5 bg-white/70" style={{ left: `${Math.min(100, mark * 100)}%` }} />}
      </div>
    </div>
  );
}

function engineState(data) {
  const r = data.risk || {};
  if (r.halted) return { label: "Pausa de segurança", dot: "bg-loss", text: "text-loss", ring: "border-loss/40" };
  if (!data.model?.loaded) return { label: "Aguardando cérebro", dot: "bg-accent", text: "text-accent", ring: "border-accent/30" };
  if (data.in_position) {
    const long = data.current_position === 1;
    return { label: long ? "Em posição · LONG" : "Em posição · SHORT", dot: long ? "bg-gain" : "bg-loss", text: long ? "text-gain" : "text-loss", ring: long ? "border-gain/30" : "border-loss/30" };
  }
  if (r.entries_blocked) return { label: "Entradas pausadas", dot: "bg-warn", text: "text-warn", ring: "border-warn/30" };
  if (r.cooldown_left > 0) return { label: "Em cooldown", dot: "bg-accent", text: "text-accent", ring: "border-accent/30" };
  return { label: "Vigilante", dot: "bg-gain", text: "text-gain", ring: "border-gain/30" };
}

export default function ControlCenter({ data }) {
  const r = data.risk || {};
  const st = engineState(data);
  const conf = r.confidence || 0;
  const thr = r.conf_threshold || 0;
  const lossLimit = Math.abs(r.daily_loss_limit_pct || 3);
  const dayLoss = Math.max(0, -(r.daily_pnl_pct || 0));
  const gen = data.model?.name?.match(/gen_(\d+)/)?.[1];

  return (
    <section className="card flex flex-col p-5">
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg border border-line bg-white/5 text-violet"><Cpu size={16} /></span>
          <div>
            <h3 className="text-sm font-bold leading-tight text-white">Centro de Controle</h3>
            <p className="text-[10px] text-slate-500">Estado do robô e proteções ativas</p>
          </div>
        </div>
        <span className={`flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold ${st.ring} ${st.text}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${st.dot} ${data.model?.loaded ? "animate-pulse" : ""}`} />
          {st.label}
        </span>
      </header>

      <p className="mt-4 rounded-xl border border-line bg-black/20 px-3 py-2.5 text-xs font-medium leading-snug text-slate-200">
        {data.status}
      </p>

      {r.entries_blocked && (
        <p className="mt-2 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] text-warn">
          Pausa de segurança: {r.entries_blocked}
        </p>
      )}

      <div className="mt-5 space-y-4">
        <Meter
          label="Convicção da IA (última vela)" value={conf} max={1} mark={thr}
          text={conf > 0 ? `${Math.round(conf * 100)}% · mín. ${Math.round(thr * 100)}%` : "aguardando"}
          tone={conf >= thr ? "bg-gain" : "bg-slate-500"}
        />
        <Meter
          label="Operações hoje" value={r.trades_today || 0} max={r.max_trades_per_day || 6}
          text={`${r.trades_today || 0} / ${r.max_trades_per_day || 6}`}
        />
        <Meter
          label="Limite de perda diária" value={dayLoss} max={lossLimit}
          text={dayLoss > 0 ? `−${dayLoss.toFixed(2)}% de −${lossLimit}%` : `sem perdas · limite −${lossLimit}%`}
          tone={dayLoss / lossLimit > 0.66 ? "bg-loss" : "bg-accent"}
        />
        <Meter
          label="Cooldown" value={r.cooldown_left || 0} max={r.cooldown_bars || 4}
          text={r.cooldown_left > 0 ? `${r.cooldown_left} vela(s)` : "livre"} tone="bg-violet"
        />
      </div>

      <ul className="mt-5 grid grid-cols-2 gap-2 text-[11px]">
        <li className="flex items-center gap-1.5 rounded-lg border border-line bg-black/20 px-2.5 py-2 text-slate-300">
          <Layers size={12} className="text-violet" /> {gen ? `Cérebro gen ${gen}` : "Cérebro gen 0 · em treino"}
        </li>
        <li className="flex items-center gap-1.5 rounded-lg border border-line bg-black/20 px-2.5 py-2 text-slate-300">
          <ShieldCheck size={12} className="text-gain" /> Simulação
        </li>
        <li className="flex items-center gap-1.5 rounded-lg border border-line bg-black/20 px-2.5 py-2 text-slate-300">
          <Target size={12} className="text-loss" /> Stop {r.stop_loss_pct ?? 1}% · Alvo {r.take_profit_pct ?? 2}%
        </li>
        <li className="flex items-center gap-1.5 rounded-lg border border-line bg-black/20 px-2.5 py-2 text-slate-300">
          <Timer size={12} className="text-accent" /> Decide a cada 15m
        </li>
      </ul>
    </section>
  );
}
