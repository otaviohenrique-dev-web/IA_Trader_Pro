"use client";

import React, { useEffect, useRef, useState } from "react";
import { Activity, CircleDot, Clock, Github, Linkedin, List, ShieldAlert, ShieldCheck, TrendingUp } from "lucide-react";
import NewsSentinel from "../components/NewsSentinel";
import ControlCenter from "../components/ControlCenter";
import TradingChart from "../components/TradingChart";
import AdminPanel from "../components/AdminPanel";
import { backendHttpBase, backendWsUrl } from "../lib/api";
import { fmtPct, fmtPrice, fmtUsd, tone } from "../lib/format";

function Kpi({ label, value, sub, valueClass = "text-white", children }) {
  return (
    <div className="card flex flex-col justify-between p-4">
      <span className="eyebrow">{label}</span>
      <div className="mt-3">
        <div className={`num text-2xl font-black leading-none sm:text-[1.65rem] ${valueClass}`}>{value}</div>
        {sub && <div className="mt-1.5 text-[11px] text-slate-500">{sub}</div>}
        {children}
      </div>
    </div>
  );
}

function PriceTicker({ price }) {
  const [tick, setTick] = useState({ price, dir: 0 });
  if (price !== tick.price) setTick({ price, dir: price > tick.price ? 1 : -1 });
  return (
    <span key={price} className={`num text-xl font-black text-white sm:text-2xl ${tick.dir > 0 ? "flash-up" : tick.dir < 0 ? "flash-down" : ""}`}>
      {price ? `$${fmtPrice(price)}` : "—"}
    </span>
  );
}

function FullScreenMessage({ icon: Icon, iconClass, title, children }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
      <Icon className={`mb-4 ${iconClass}`} size={44} />
      <p className="text-lg font-bold text-white">{title}</p>
      <div className="mt-2 max-w-md text-sm text-slate-400">{children}</div>
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [wsLive, setWsLive] = useState(false);
  const ws = useRef(null);
  const reconnectRef = useRef(null);

  useEffect(() => {
    const httpBase = backendHttpBase();
    const wsUrl = backendWsUrl();
    let cancelled = false;
    let wsConnected = false;

    const apply = (next) =>
      setData((prev) => (!prev || prev.error || JSON.stringify(prev) !== JSON.stringify(next) ? next : prev));

    const pullState = async () => {
      if (wsConnected) return;
      try {
        const res = await fetch(`${httpBase}/api/state`);
        if (cancelled) return;
        if (!res.ok) { setData({ error: `Servidor respondeu HTTP ${res.status}. Pode estar iniciando ou offline.` }); setWsLive(false); return; }
        const text = await res.text();
        if (!text) { setData({ error: "API retornou resposta vazia." }); setWsLive(false); return; }
        apply(JSON.parse(text));
      } catch (err) {
        if (!cancelled) { setData({ error: `Erro de rede/CORS: ${err.message}` }); setWsLive(false); }
      }
    };

    const connectWS = () => {
      if (cancelled) return;
      try {
        ws.current = new WebSocket(wsUrl);
        ws.current.onopen = () => { if (!cancelled) { wsConnected = true; setWsLive(true); } };
        ws.current.onmessage = (event) => {
          if (cancelled) return;
          try { apply(JSON.parse(event.data)); } catch (err) { console.error("[WS] parse:", err); }
        };
        ws.current.onclose = () => {
          if (cancelled) return;
          wsConnected = false; setWsLive(false);
          reconnectRef.current = setTimeout(connectWS, 3000);
        };
        ws.current.onerror = () => ws.current?.close();
      } catch (err) { console.error("[WS] falha na inicialização:", err); }
    };

    pullState();
    connectWS();
    const poll = setInterval(pullState, 5000);
    return () => {
      cancelled = true;
      clearInterval(poll);
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      ws.current?.close();
    };
  }, []);

  if (!data) {
    return (
      <FullScreenMessage icon={Activity} iconClass="animate-spin text-accent" title="Conectando ao robô…">
        O servidor gratuito pode levar até um minuto para acordar.
      </FullScreenMessage>
    );
  }

  if (data.error) {
    return (
      <FullScreenMessage icon={ShieldAlert} iconClass="text-warn" title="Servidor não respondeu">
        <p>Verifique a variável <code className="text-accent">NEXT_PUBLIC_API_URL</code> na Vercel.</p>
        <p className="num mt-3 break-all text-xs text-slate-500">Endereço: {backendHttpBase()}</p>
        <p className="mt-3 rounded-lg border border-loss/30 bg-loss/10 p-2 text-xs text-loss">{data.error}</p>
        <p className="mt-3 text-xs text-slate-500">Tentando novamente em 5 segundos…</p>
      </FullScreenMessage>
    );
  }

  const risk = data.risk || {};
  const live = data.last_candle || {};
  const price = live.close || 0;
  const ema50 = live.ema50_4h || 0;
  const ema200 = live.ema200_4h || 0;
  const bullish = price > ema200;
  const balance = data.display_balance ?? data.balance ?? 0;
  const start = data.starting_balance || 100;
  const totalRet = (balance / start - 1) * 100;
  const trades = (data.adaptation?.wins || 0) + (data.adaptation?.losses || 0);
  const pf = risk.profit_factor;

  return (
    <div className="mx-auto min-h-screen max-w-[1600px] overflow-x-clip px-4 py-5 sm:px-6 lg:px-8">
      {/* ---------- Cabeçalho ---------- */}
      <header className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-linear-to-br from-accent to-violet shadow-lg shadow-accent/20">
            <TrendingUp size={20} className="text-ink" strokeWidth={2.6} />
          </span>
          <div>
            <h1 className="text-lg font-black leading-tight tracking-tight text-white">IA Trader Pro</h1>
            <p className="text-[11px] text-slate-500">Terminal de trading assistido por IA · BTC/USDT</p>
          </div>
          <span className="ml-1 hidden rounded-full border border-warn/30 bg-warn/10 px-2.5 py-1 text-[10px] font-bold text-warn sm:inline">
            SIMULAÇÃO · sem dinheiro real
          </span>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="eyebrow">Bitcoin</div>
            <PriceTicker price={price} />
          </div>
          <div className="hidden h-9 w-px bg-line sm:block" />
          <div className="flex flex-col items-end gap-1.5">
            <span className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold ${
              wsLive ? "border-gain/30 bg-gain/10 text-gain" : "border-warn/30 bg-warn/10 text-warn"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${wsLive ? "bg-gain animate-pulse" : "bg-warn"}`} />
              {wsLive ? "Tempo real" : "Reconectando…"}
            </span>
            <span className="num flex items-center gap-1 text-[11px] text-slate-500"><Clock size={11} /> {data.uptime}</span>
          </div>
        </div>
      </header>

      {/* ---------- Indicadores ---------- */}
      <section className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5 [&>*]:min-w-0">
        <Kpi label="Patrimônio" value={fmtUsd(balance)} valueClass={tone(data.floating_pnl)}
          sub={<span className={tone(totalRet)}>{fmtPct(totalRet)} desde o início</span>} />
        <Kpi label="Resultado do dia" value={fmtPct(risk.daily_pnl_pct || 0)} valueClass={tone(risk.daily_pnl_pct)}
          sub={`${risk.trades_today || 0} operação(ões) hoje`} />
        <Kpi label="Taxa de acerto" value={trades ? `${data.adaptation?.current_win_rate ?? 0}%` : "—"}
          sub={trades ? `${data.adaptation.wins} ganhos · ${data.adaptation.losses} perdas` : "sem operações ainda"} />
        <Kpi label="Fator de lucro" value={pf > 0 ? pf.toFixed(2) : "—"} valueClass={pf >= 1 ? "text-gain" : pf > 0 ? "text-loss" : "text-white"}
          sub={pf > 0 ? (pf >= 1 ? "ganhos superam perdas" : "perdas superam ganhos") : "aguardando histórico"} />
        <Kpi label="Queda máxima" value={fmtPct(risk.max_drawdown_pct || 0)} valueClass={risk.max_drawdown_pct < 0 ? "text-loss" : "text-white"}
          sub="pior recuo do patrimônio" />
      </section>

      {/* ---------- Gráfico + Analista ---------- */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12 [&>*]:min-w-0">
        <section className="card flex flex-col overflow-hidden xl:col-span-9">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-bold text-white">
              <Activity size={15} className="text-accent" /> Gráfico tático
            </h2>
            {ema200 > 0 ? (
              <div className="flex items-center gap-3 rounded-full border border-line bg-black/20 px-3 py-1.5">
                <span className={`flex items-center gap-1.5 text-[11px] font-bold ${bullish ? "text-gain" : "text-loss"}`}>
                  <CircleDot size={11} className="animate-pulse" /> Tendência macro: {bullish ? "alta" : "baixa"}
                </span>
                <span className="num hidden text-[10px] text-slate-500 md:inline">
                  EMA50 4H {fmtPrice(ema50)} · EMA200 4H {fmtPrice(ema200)}
                </span>
              </div>
            ) : (
              <span className="animate-pulse text-[11px] text-slate-500">Sincronizando visão macro…</span>
            )}
          </div>
          <div className="min-h-0 flex-1">
          <TradingChart
            liveCandle={data.last_candle}
            markersData={data.markers}
            inPosition={data.in_position}
            entryPrice={data.entry_price}
            currentPosition={data.current_position}
            risk={risk}
          />
          </div>
        </section>

        <aside className="flex min-w-0 flex-col gap-5 xl:col-span-3">
          <NewsSentinel data={data.news_agent} />
          <ControlCenter data={data} />
        </aside>
      </div>

      {/* ---------- Livro de ações + Admin ---------- */}
      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-3 [&>*]:min-w-0">
        <section className="card flex h-80 flex-col p-4 lg:col-span-1">
          <h2 className="mb-3 flex shrink-0 items-center gap-2 border-b border-line pb-3 text-sm font-bold text-white">
            <List size={15} className="text-violet" /> Livro de ações
          </h2>
          <div className="thin-scroll flex-1 space-y-2 overflow-y-auto pr-1">
            {data.order_book?.length ? (
              data.order_book.map((o, i) => {
                const m = o.text.match(/^\[(.*?)\]\s*(.*)$/);
                return (
                  <div key={i} className="rounded-lg border border-line bg-black/20 px-3 py-2 text-[11px] leading-snug text-slate-300">
                    {m && <span className="num mr-2 text-slate-500">{m[1]}</span>}{m ? m[2] : o.text}
                  </div>
                );
              })
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-slate-600">
                <ShieldCheck size={26} />
                <span className="text-xs">Nenhuma operação ainda.<br />O robô só entra quando a convicção é alta.</span>
              </div>
            )}
          </div>
        </section>

        <div className="lg:col-span-2"><AdminPanel model={data.model} /></div>
      </div>

      <footer className="mt-10 flex flex-col items-center justify-between gap-4 border-t border-line pt-6 text-sm text-slate-500 md:flex-row">
        <p className="text-center leading-relaxed md:text-left">
          © {new Date().getFullYear()} <span className="text-slate-400">Otávio Henrique Filgueiras dos Santos</span>
          <span className="mt-1 block text-xs text-slate-600">IA Trader Pro — monitoramento e simulação. Não é recomendação de investimento.</span>
        </p>
        <nav className="flex items-center gap-5" aria-label="Redes sociais">
          <a href="https://www.linkedin.com/in/otaviohenrique-dev/" target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 text-slate-400 transition-colors hover:text-[#4aa3ff]">
            <Linkedin size={18} aria-hidden /> <span className="text-xs font-semibold">LinkedIn</span>
          </a>
          <a href="https://github.com/otaviohenrique-dev-web" target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 text-slate-400 transition-colors hover:text-white">
            <Github size={18} aria-hidden /> <span className="text-xs font-semibold">GitHub</span>
          </a>
        </nav>
      </footer>
    </div>
  );
}
