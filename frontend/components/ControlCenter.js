import React from "react";
import { Cpu, ShieldCheck, Timer, Layers, Radar, BadgeCheck } from "lucide-react";

function Meter({ label, value, max, text, tone = "bg-accent" }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-[11px]">
        <span className="font-medium text-slate-400">{label}</span>
        <span className="num font-semibold text-slate-200">{text}</span>
      </div>
      <div className="relative h-1.5 overflow-hidden rounded-full bg-white/5">
        <div className={`h-full rounded-full transition-all duration-700 ${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function engineState(data) {
  const r = data.risk || {};
  if (r.halted) return { label: "Pausa de segurança", dot: "bg-loss", text: "text-loss", ring: "border-loss/40" };
  if (!data.model?.loaded) return { label: "Aguardando cérebro", dot: "bg-accent", text: "text-accent", ring: "border-accent/30" };
  if (data.model?.selftest?.ok === false) return { label: "Auto-verificação falhou", dot: "bg-loss", text: "text-loss", ring: "border-loss/40" };
  if (r.open_positions > 0) return { label: `${r.open_positions} posição(ões)`, dot: "bg-accent", text: "text-accent", ring: "border-accent/30" };
  if (r.entries_blocked) return { label: "Entradas pausadas", dot: "bg-warn", text: "text-warn", ring: "border-warn/30" };
  return { label: "Vigilante", dot: "bg-gain", text: "text-gain", ring: "border-gain/30" };
}

function eta(sec) {
  if (sec == null) return "—";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export default function ControlCenter({ data }) {
  const r = data.risk || {};
  const pf = data.portfolio || {};
  const st = engineState(data);
  const lossLimit = Math.abs(r.daily_loss_limit_pct || 3);
  const dayLoss = Math.max(0, -(r.daily_pnl_pct || 0));
  const gen = data.model?.name?.match(/gen_(\d+)/)?.[1];
  const self = data.model?.selftest;

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

      <p className="mt-4 rounded-xl border border-line bg-black/20 px-3 py-2.5 text-xs font-medium leading-snug text-slate-200">{data.status}</p>

      {r.entries_blocked && (
        <p className="mt-2 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] text-warn">Pausa de segurança: {r.entries_blocked}</p>
      )}

      <div className="mt-5 space-y-4">
        <Meter label="Posições abertas" value={r.open_positions || 0} max={r.max_positions || 3} text={`${r.open_positions || 0} / ${r.max_positions || 3}`} />
        <Meter label="Entradas hoje" value={r.trades_today || 0} max={r.max_trades_per_day || 4} text={`${r.trades_today || 0} / ${r.max_trades_per_day || 4}`} tone="bg-violet" />
        <Meter label="Limite de perda diária" value={dayLoss} max={lossLimit}
          text={dayLoss > 0 ? `−${dayLoss.toFixed(2)}% de −${lossLimit}%` : `sem perdas · limite −${lossLimit}%`}
          tone={dayLoss / lossLimit > 0.66 ? "bg-loss" : "bg-accent"} />
      </div>

      <ul className="mt-5 grid grid-cols-2 gap-2 text-[11px]">
        <li className="flex items-center gap-1.5 rounded-lg border border-line bg-black/20 px-2.5 py-2 text-slate-300">
          <Layers size={12} className="text-violet" /> {gen ? `Cérebro gen ${gen}` : "Sem cérebro"}
        </li>
        <li className="flex items-center gap-1.5 rounded-lg border border-line bg-black/20 px-2.5 py-2 text-slate-300">
          <ShieldCheck size={12} className="text-gain" /> Simulação
        </li>
        <li className="flex items-center gap-1.5 rounded-lg border border-line bg-black/20 px-2.5 py-2 text-slate-300">
          <Radar size={12} className="text-accent" /> Risco {(r.risk_per_trade_pct || 0).toFixed(1)}% por trade
        </li>
        <li className="flex items-center gap-1.5 rounded-lg border border-line bg-black/20 px-2.5 py-2 text-slate-300">
          <Timer size={12} className="text-accent" /> Próxima vela: {eta(pf.next_bar_in)}
        </li>
        {self && self.ok != null && (
          <li className={`col-span-2 flex items-center gap-1.5 rounded-lg border px-2.5 py-2 ${self.ok ? "border-gain/20 bg-gain/5 text-gain" : "border-loss/30 bg-loss/10 text-loss"}`}>
            <BadgeCheck size={12} /> Auto-verificação {self.ok ? "ok" : "FALHOU"}: <span className="text-[10px] opacity-80">{self.detail}</span>
          </li>
        )}
      </ul>
      {data.model?.status && (
        <p className="mt-3 rounded-lg border border-warn/20 bg-warn/5 px-2.5 py-2 text-[10px] leading-snug text-warn/90">{data.model.status}</p>
      )}
    </section>
  );
}
