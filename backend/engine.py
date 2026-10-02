"""
Motor MULTI-ATIVO ao vivo (SIMULAÇÃO: nenhuma ordem real). Aplica o pacote de modelo `models/gen_N.{onnx,json}`:

  - lê velas de 4H dos 4 pares (Binance; reserva: Kraken), mantém ~500 dias de histórico por par;
  - a cada vela fechada calcula as variáveis (mesmo código do treino), roda o modelo e obtém o GANHO ESPERADO (EV, em R) de
    comprar cada par; só entra se o EV passar do limiar e o regime do BTC for de alta;
  - portfólio: até 3 posições (máx. 2 na mesma direção), risco de 0,8% por operação, stop/alvo/tempo, limites diários,
    freio de volatilidade e kill-switch global;
  - auto-verificação na partida: compara o cálculo do servidor com valores de referência gravados no treino.
"""
import asyncio
import glob
import json
import os
import re
import time
from datetime import datetime, timezone

import aiohttp
import ccxt.async_support as ccxt
import numpy as np
import onnxruntime as ort
import pandas as pd

import live_model as L

MODELS_DIR = "models"
POLL_SECONDS = 30
STARTING_BALANCE = float(os.environ.get("STARTING_BALANCE", 1000.0))
KILL_SWITCH_DD = float(os.environ.get("KILL_SWITCH_DD", 0.25))     # queda desde o pico que pausa TUDO (reativação manual)
SELFTEST_TOL = 0.03                                               # diferença máxima de EV aceita na auto-verificação
SYMS = {a: f"{a}/USDT" for a in L.ASSETS}


def _softmax(z):
    z = z - z.max(-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(-1, keepdims=True)


def find_package():
    """Maior geração disponível em models/ que tenha o par .onnx + .json."""
    best, best_n = None, -1
    for p in glob.glob(os.path.join(MODELS_DIR, "gen_*.onnx")):
        m = re.search(r"gen_(\d+)\.onnx$", p)
        if m and os.path.exists(p[:-5] + ".json") and int(m.group(1)) > best_n:
            best, best_n = p[:-5], int(m.group(1))
    return best


def new_state():
    return {
        "eq": STARTING_BALANCE, "peak": STARTING_BALANCE, "max_dd": 0.0, "positions": [], "cooldown": {a: 0 for a in L.ASSETS},
        "day": "", "day_start": STARTING_BALANCE, "trades_today": 0, "wins": 0, "losses": 0, "gross_win": 0.0, "gross_loss": 0.0,
        "halted": False, "breaker_until": 0, "last_bar_ts": 0, "trade_log": [], "news_events": [],
        "markers": {a: [] for a in L.ASSETS}, "order_book": [],
    }


class Engine:
    def __init__(self, notify, news_status):
        self.notify, self.news_status = notify, news_status
        self.st = new_state()
        self.bars = {}                  # ativo -> DataFrame de velas de 4h FECHADAS
        self.forming = {}               # ativo -> vela em formação
        self.ex = None
        self._session = None
        self.ex_name = ""
        self.sess = None
        self.cfg = None
        self.pkg = None
        self.selftest = {"ok": None, "detail": "aguardando"}
        self.radar = {a: {"status": "aguardando", "ev": None} for a in L.ASSETS}
        self.regime_ok = None
        self.last_error = ""
        self.note = ""
        self.ready_bars = False
        self.dirty = False

    def now_ms(self):
        """Relógio do motor (injetável para simular o passado nos testes)."""
        return int(time.time() * 1000)

    # ------------------------------------------------------------------ modelo
    def load_package(self, base=None):
        """Carrega e VALIDA o pacote; só substitui o atual se tudo estiver coerente."""
        base = base or find_package()
        if not base:
            return False, "nenhum pacote gen_N.onnx + gen_N.json em models/"
        try:
            with open(base + ".json", encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg["features"] != L.FEATURES or cfg["lags"] != L.LAGS or cfg["assets"] != L.ASSETS:
                raise ValueError("pacote incompatível com as variáveis/ativos do servidor")
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            sess = ort.InferenceSession(base + ".onnx", sess_options=opts, providers=["CPUExecutionProvider"])
            if sess.get_inputs()[0].shape[1] != L.LAGS * len(L.FEATURES):
                raise ValueError("entrada do ONNX com tamanho inesperado")
        except Exception as e:
            return False, f"pacote rejeitado: {e}"
        self.sess, self.cfg, self.pkg = sess, cfg, os.path.basename(base)
        self.selftest = {"ok": None, "detail": "aguardando"}
        return True, ""

    @property
    def loaded(self):
        return self.sess is not None

    # ------------------------------------------------------------- exchange
    async def _make_exchange(self, name):
        # resolvedor por threads: o padrão (aiodns) falha em alguns ambientes (ex.: Windows) e o ThreadedResolver funciona em todos
        self._session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver()))
        ex = getattr(ccxt, name)({"enableRateLimit": True, "timeout": 30000, "session": self._session})
        await ex.load_markets()
        return ex

    async def ensure_exchange(self):
        if self.ex is not None:
            return
        last = None
        for name in ("binance", "kraken"):
            try:
                self.ex = await self._make_exchange(name)
                await self.ex.fetch_ohlcv(SYMS["BTC"], "4h", limit=2)
                self.ex_name = name
                return
            except Exception as e:
                last = e
                await self.close()
        raise RuntimeError(f"nenhuma corretora acessível ({type(last).__name__})")

    async def _history(self, asset, n):
        """Pagina para trás no tempo (do mais antigo ao mais novo) até ter `n` velas fechadas de 4h."""
        now = self.now_ms()
        since = now - (n + 5) * L.H4
        rows = []
        while since < now:
            batch = await self.ex.fetch_ohlcv(SYMS[asset], "4h", since=since, limit=1000)
            if not batch:
                break
            rows += batch
            nxt = batch[-1][0] + 1
            if nxt <= since or len(batch) < 2:
                break
            since = nxt
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"]).drop_duplicates("timestamp")
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df[df["timestamp"] + L.H4 <= now].reset_index(drop=True)

    async def init_history(self):
        await self.ensure_exchange()
        for a in L.ASSETS:
            self.bars[a] = await self._history(a, L.MIN_BARS)
        self.ready_bars = all(len(b) >= L.MIN_BARS - 50 for b in self.bars.values())
        if not self.ready_bars:
            self.note = (f"histórico insuficiente na fonte '{self.ex_name}' "
                         f"({min(len(b) for b in self.bars.values())}/{L.MIN_BARS} velas): só observação, sem operar")

    async def poll_prices(self):
        """Uma chamada por ativo: vela em formação (preço ao vivo) + detecção de vela nova."""
        now = self.now_ms()

        async def one(a):
            return a, await self.ex.fetch_ohlcv(SYMS[a], "4h", limit=3)
        got = await asyncio.gather(*[one(a) for a in L.ASSETS])
        new_closed = {}
        for a, rows in got:
            if not rows:
                continue
            closed = [r for r in rows if r[0] + L.H4 <= now]
            form = [r for r in rows if r[0] + L.H4 > now]
            self.forming[a] = form[-1] if form else None
            new_closed[a] = closed
        return new_closed

    async def merge_closed(self, asset):
        last = int(self.bars[asset]["timestamp"].iloc[-1])
        batch = await self.ex.fetch_ohlcv(SYMS[asset], "4h", since=last + 1, limit=100)
        now = self.now_ms()
        rows = [r for r in batch if r[0] > last and r[0] + L.H4 <= now]
        if rows:
            add = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
            self.bars[asset] = pd.concat([self.bars[asset], add], ignore_index=True).iloc[-(L.MIN_BARS + 200):].reset_index(drop=True)

    # ------------------------------------------------------------- sinais
    def compute_signals(self):
        """Variáveis -> modelo -> EV por ativo (síncrono; roda em thread). Retorna dict por ativo e o contexto do BTC."""
        feats = L.features_for_all(self.bars)
        ts_last = {a: int(f["timestamp"].iloc[-1]) for a, f in feats.items()}
        rows, order = [], []
        for a in L.ASSETS:
            f = feats[a].tail(L.LAGS)
            if len(f) < L.LAGS or f[L.FEATURES].isna().any().any():
                continue
            rows.append(L.normalize(f, self.cfg["stats"][a]).reshape(-1))
            order.append(a)
        out = {"ts": ts_last, "assets": {}}
        if rows:
            logits = self.sess.run(None, {"x": np.stack(rows).astype(np.float32)})[0]
            p = _softmax(logits)
            for k, a in enumerate(order):
                last = feats[a].iloc[-1]
                stop = float(L.stop_pct(last["atr_pct"]))
                out["assets"][a] = {
                    "ev": float(L.expected_value(p[k, 0], p[k, 1], stop)), "p_win": float(p[k, 0]), "p_loss": float(p[k, 1]),
                    "stop": stop, "close": float(last["close"]), "ts": int(last["timestamp"]),
                    "dist_ema200": float(last["dist_ema200"]), "rsi": float(last["rsi"]),
                    "ema50": float(last["close"] / (1 + last["dist_ema50"] / 100)),
                    "ema200": float(last["close"] / (1 + last["dist_ema200"] / 100)),
                }
        out["btc_dist200"] = float(feats["BTC"]["btc_dist200"].iloc[-1])
        # auto-verificação: as velas de referência gravadas no treino reproduzem o mesmo EV?
        if self.selftest["ok"] is None:
            diffs = []
            for a in L.ASSETS:
                ref = {r["ts"]: r["ev"] for r in self.cfg.get("reference", {}).get(a, [])}
                f = feats[a]
                idx = {int(t): i for i, t in enumerate(f["timestamp"])}
                for t, ev_ref in ref.items():
                    if t in idx and idx[t] >= L.LAGS:
                        win = f.iloc[idx[t] - L.LAGS + 1: idx[t] + 1]
                        x = L.normalize(win, self.cfg["stats"][a]).reshape(1, -1).astype(np.float32)
                        pp = _softmax(self.sess.run(None, {"x": x})[0])[0]
                        stop = float(L.stop_pct(win["atr_pct"].iloc[-1]))
                        diffs.append(abs(float(L.expected_value(pp[0], pp[1], stop)) - ev_ref))
            if diffs:
                worst = max(diffs)
                self.selftest = {"ok": bool(worst < SELFTEST_TOL), "detail": f"{len(diffs)} velas comparadas; diferença máxima de EV {worst:.4f}"}
            else:
                self.selftest = {"ok": True, "detail": "sem velas de referência no histórico atual (não verificado)"}
        return out

    # ------------------------------------------------------------ portfólio
    def mtm(self):
        unreal = 0.0
        for p in self.st["positions"]:
            px = self.price(p["asset"])
            unreal += p["notional"] * (px / p["entry"] - 1.0)
        return self.st["eq"] + unreal, unreal

    def price(self, a):
        f = self.forming.get(a)
        if f:
            return float(f[4])
        return float(self.bars[a]["close"].iloc[-1]) if a in self.bars else 0.0

    def _book(self, text):
        self.st["order_book"] = ([{"text": f"[{datetime.fromtimestamp(self.now_ms() / 1000).strftime('%d/%m %H:%M')}] {text}"}] + self.st["order_book"])[:80]

    def _mark(self, asset, bar_ts, kind, win=None):
        sec = int(bar_ts // 1000)
        if kind == "in":
            m = {"time": sec, "position": "belowBar", "color": "#34d399", "shape": "arrowUp", "text": "COMPRA"}
        else:
            m = {"time": sec, "position": "aboveBar", "color": "#34d399" if win else "#fb7185", "shape": "circle",
                 "text": "GANHO" if win else "PERDA"}
        self.st["markers"][asset] = (self.st["markers"][asset] + [m])[-60:]

    def open_position(self, asset, price, s, ev, ref_bar_ts):
        eq_now, _ = self.mtm()
        total = sum(p["notional"] for p in self.st["positions"])
        c = self.cfg
        notional = min(eq_now * c["risk"] / s, c["portfolio"]["max_lev_pos"] * eq_now, c["portfolio"]["max_lev_total"] * eq_now - total)
        if notional <= 0:
            return False
        self.st["eq"] -= notional * L.COST
        pos = {"asset": asset, "entry": price, "stop": price * (1 - s), "tp": price * (1 + L.RR * s), "notional": notional,
               "s": s, "opened_ts": self.now_ms(), "opened_bar": int(ref_bar_ts) + L.H4, "eq0": eq_now,
               "news": self.news_status(), "ev": ev}
        self.st["positions"].append(pos)
        self.st["trades_today"] += 1
        self._mark(asset, pos["opened_bar"], "in")
        self._book(f"🚀 Comprou {asset} a US$ {price:,.2f} | stop {pos['stop']:,.2f} | alvo {pos['tp']:,.2f} | EV {ev:+.2f}R")
        self.notify(f"🚀 {asset} comprado a US$ {price:,.2f} (simulação)\nStop {pos['stop']:,.2f} · Alvo {pos['tp']:,.2f} · EV {ev:+.2f}R")
        self.dirty = True
        return True

    def close_position(self, pos, px, reason):
        pnl = pos["notional"] * (px / pos["entry"] - 1.0)
        fee = pos["notional"] * L.COST
        self.st["eq"] += pnl - fee
        net = pnl - fee - pos["notional"] * L.COST            # líquido do trade (entrada + saída)
        win = net > 0
        self.st["wins" if win else "losses"] += 1
        self.st["gross_win" if win else "gross_loss"] += abs(net)
        self.st["positions"] = [p for p in self.st["positions"] if p is not pos]
        self.st["cooldown"][pos["asset"]] = L.CFG["cooldown"]
        self.st["trade_log"] = (self.st["trade_log"] + [{
            "asset": pos["asset"], "open_ts": pos["opened_ts"], "close_ts": self.now_ms(), "entry": pos["entry"],
            "exit": px, "net": round(net, 4), "net_pct": round(net / pos["eq0"] * 100, 3), "reason": reason, "news": pos["news"]}])[-500:]
        bar_ts = (self.now_ms() // L.H4) * L.H4
        self._mark(pos["asset"], bar_ts, "out", win)
        self._book(f"🏁 Fechou {pos['asset']} ({reason}) a US$ {px:,.2f} | líquido US$ {net:+.2f} {'✅' if win else '❌'}")
        self.notify(f"🏁 {pos['asset']} fechado ({reason})\nResultado líquido: US$ {net:+.2f}\nPatrimônio: US$ {self.mtm()[0]:,.2f} (simulação)")
        eq_now = self.mtm()[0]
        self.st["peak"] = max(self.st["peak"], eq_now)
        self.st["max_dd"] = min(self.st["max_dd"], eq_now / self.st["peak"] - 1)
        self.dirty = True

    def block_reason(self):
        s, now = self.st, self.now_ms()
        if s["halted"]:
            return f"kill-switch: queda de {KILL_SWITCH_DD * 100:.0f}% desde o pico (reative no painel admin)"
        if self.mtm()[0] / s["day_start"] - 1 <= L.CFG["daily_loss"]:
            return f"limite de perda diária ({L.CFG['daily_loss'] * 100:.0f}%)"
        if now < s["breaker_until"]:
            return "freio de volatilidade (movimento brusco do BTC)"
        if s["trades_today"] >= L.CFG["max_trades_day"]:
            return f"limite de {L.CFG['max_trades_day']} entradas por dia"
        if self.regime_ok is False:
            return "regime de baixa do BTC (abaixo da média de 200 períodos)"
        return ""

    def roll_day(self):
        today = datetime.fromtimestamp(self.now_ms() / 1000, timezone.utc).strftime("%Y-%m-%d")
        if self.st["day"] != today:
            self.st["day"], self.st["day_start"], self.st["trades_today"] = today, self.mtm()[0], 0

    def check_stops_live(self):
        """Stop/alvo com o preço ao vivo (a cada POLL_SECONDS)."""
        for pos in list(self.st["positions"]):
            px = self.price(pos["asset"])
            if px <= 0:
                continue
            if px <= pos["stop"]:
                self.close_position(pos, px, "STOP-LOSS")
            elif px >= pos["tp"]:
                self.close_position(pos, px, "ALVO")

    def check_closed_bar(self, asset, bar):
        """Stop/alvo/tempo usando a máxima e a mínima da vela fechada (pega o que o polling perdeu). Retorna True se fechou."""
        for pos in [p for p in self.st["positions"] if p["asset"] == asset]:
            ts, o, h, l, c = bar[:5]
            if ts < pos["opened_bar"]:
                continue
            if o <= pos["stop"]:
                self.close_position(pos, o, "STOP-LOSS"); continue
            if l <= pos["stop"]:
                self.close_position(pos, pos["stop"], "STOP-LOSS"); continue
            if h >= pos["tp"]:
                self.close_position(pos, max(pos["tp"], o), "ALVO"); continue
            if (ts - pos["opened_bar"]) // L.H4 + 1 >= L.HOLD:
                self.close_position(pos, c, "TEMPO")

    def kill_switch(self):
        if self.st["halted"]:
            return
        eq_now = self.mtm()[0]
        self.st["peak"] = max(self.st["peak"], eq_now)
        if eq_now / self.st["peak"] - 1 <= -KILL_SWITCH_DD:
            for pos in list(self.st["positions"]):
                self.close_position(pos, self.price(pos["asset"]), "KILL-SWITCH")
            self.st["halted"] = True
            self.note = "🛑 KILL-SWITCH ACIONADO"
            self.notify(f"🛑 KILL-SWITCH: queda de {KILL_SWITCH_DD * 100:.0f}% desde o pico. Robô PAUSADO até reativar no painel.\n"
                        f"Patrimônio: US$ {self.mtm()[0]:,.2f}")
            self.dirty = True

    def resume(self):
        self.st["halted"], self.st["peak"] = False, self.mtm()[0]
        self.note = ""
        self.dirty = True

    # ------------------------------------------------------------- ciclo
    async def decision_step(self, sig, allow_entries=True):
        """Chamado UMA vez por vela fechada de 4h. `allow_entries=False` só atualiza o radar (ex.: logo após reiniciar)."""
        s, c, now = self.st, self.cfg, self.now_ms()
        a_sig = sig["assets"]
        self.regime_ok = sig["btc_dist200"] > 0
        # freio de volatilidade: movimento do BTC em 1 e 3 velas
        cl = self.bars["BTC"]["close"].to_numpy()
        cfg = L.CFG
        if len(cl) > cfg["breaker_lb"] + 1 and (abs(cl[-1] / cl[-2] - 1) >= cfg["breaker_1"] or abs(cl[-1] / cl[-1 - cfg["breaker_lb"]] - 1) >= cfg["breaker_n"]):
            if now >= s["breaker_until"]:
                self.notify("🧯 Freio de volatilidade: movimento brusco do BTC. Novas entradas pausadas.")
            s["breaker_until"] = now + cfg["breaker_bars"] * L.H4
        for a in L.ASSETS:
            s["cooldown"][a] = max(0, s["cooldown"][a] - 1)
        self.roll_day()
        # radar
        for a, d in a_sig.items():
            self.radar[a] = {**d, "status": ""}
        if not allow_entries or not self.loaded or not self.ready_bars or self.selftest["ok"] is False:
            return
        # candidatas
        held = {p["asset"] for p in s["positions"]}
        cands = [(d["ev"], a) for a, d in a_sig.items() if a not in held and s["cooldown"][a] == 0 and d["ev"] >= c["thr"]]
        cands.sort(reverse=True)
        n_pos = len(s["positions"])
        for ev, a in cands:
            if self.block_reason():
                break
            if n_pos >= cfg["max_pos"] or n_pos >= cfg["max_same_dir"]:        # só comprados: mesma direção = tudo
                break
            price = self.price(a) or a_sig[a]["close"]
            if self.open_position(a, price, a_sig[a]["stop"], ev, a_sig[a]["ts"]):
                n_pos += 1

    async def tick(self):
        await self.ensure_exchange()
        if not self.bars:
            await self.init_history()
        new_closed = await self.poll_prices()
        self.roll_day()
        self.check_stops_live()
        self.kill_switch()
        btc_closed = new_closed.get("BTC", [])
        last_btc = int(self.bars["BTC"]["timestamp"].iloc[-1])
        if btc_closed and btc_closed[-1][0] > last_btc:                     # vela nova de 4h fechou
            for a in L.ASSETS:
                before = int(self.bars[a]["timestamp"].iloc[-1])
                await self.merge_closed(a)
                for r in [x for x in new_closed.get(a, []) if x[0] > before]:
                    self.check_closed_bar(a, r)
            if self.loaded and self.ready_bars:
                sig = await asyncio.to_thread(self.compute_signals)
                # só entra se a vela acabou de fechar (como no backtest: decide no fechamento, entra na abertura seguinte)
                fresh = self.now_ms() - (btc_closed[-1][0] + L.H4) <= 15 * 60 * 1000
                await self.decision_step(sig, allow_entries=fresh)
            self.st["last_bar_ts"] = int(self.bars["BTC"]["timestamp"].iloc[-1])
            self.dirty = True
        elif self.loaded and self.ready_bars and self.radar["BTC"].get("status") == "aguardando":
            sig = await asyncio.to_thread(self.compute_signals)               # primeira leitura após a partida: só radar
            await self.decision_step(sig, allow_entries=False)
            self.st["last_bar_ts"] = int(self.bars["BTC"]["timestamp"].iloc[-1])
        self.last_error = ""

    # ------------------------------------------------------------- estado
    def asset_status(self, a):
        d = self.radar.get(a, {})
        if any(p["asset"] == a for p in self.st["positions"]):
            return "em posição"
        if self.st["cooldown"].get(a, 0) > 0:
            return "em cooldown"
        if d.get("ev") is None:
            return "aguardando"
        if self.regime_ok is False:
            return "regime de baixa"
        return "oportunidade" if d["ev"] >= (self.cfg or {}).get("thr", 9) else "sem oportunidade"

    def headline(self):
        if not self.loaded:
            return "⏳ Aguardando o primeiro cérebro (nenhum pacote gen_N válido em models/)"
        if self.note:
            return self.note
        if not self.ready_bars:
            return "⏳ Carregando histórico de mercado…"
        if self.selftest["ok"] is False:
            return f"⛔ Auto-verificação FALHOU ({self.selftest['detail']}): sem operar"
        if self.st["positions"]:
            return f"📊 {len(self.st['positions'])} posição(ões) aberta(s)"
        b = self.block_reason()
        return f"⏳ Entradas pausadas: {b}" if b else "🔍 Buscando oportunidades nos 4 pares…"

    def public(self):
        eq_now, unreal = self.mtm()
        s, thr = self.st, (self.cfg or {}).get("thr")
        assets = {}
        for a in L.ASSETS:
            f = self.forming.get(a)
            d = self.radar.get(a, {})
            pos = next((p for p in s["positions"] if p["asset"] == a), None)
            assets[a] = {
                "price": self.price(a), "ev": d.get("ev"), "p_win": d.get("p_win"), "p_loss": d.get("p_loss"), "stop_pct": d.get("stop"),
                "dist_ema200": d.get("dist_ema200"), "rsi": d.get("rsi"), "ema50": d.get("ema50"), "ema200": d.get("ema200"),
                "status": self.asset_status(a), "cooldown": s["cooldown"].get(a, 0),
                "candle": ({"time": int(f[0] // 1000), "open": f[1], "high": f[2], "low": f[3], "close": f[4]} if f else None),
                "position": ({"entry": pos["entry"], "stop": pos["stop"], "tp": pos["tp"], "notional": pos["notional"]} if pos else None),
            }
        positions = []
        for p in s["positions"]:
            px = self.price(p["asset"])
            held = max(1, (self.now_ms() - p["opened_bar"]) // L.H4 + 1) if p["opened_bar"] else 1
            positions.append({"asset": p["asset"], "entry": p["entry"], "price": px, "stop": p["stop"], "tp": p["tp"],
                              "notional": p["notional"], "pnl_pct": (px / p["entry"] - 1) * 100,
                              "pnl_usd": p["notional"] * (px / p["entry"] - 1), "bars_held": int(held), "hold_max": L.HOLD})
        nxt = L.H4 - (self.now_ms() % L.H4)
        n = s["wins"] + s["losses"]
        return {
            "assets": assets, "positions": positions, "thr": thr, "regime_ok": self.regime_ok, "next_bar_in": int(nxt // 1000),
            "source": self.ex_name, "selftest": self.selftest, "headline": self.headline(),
            "equity": eq_now, "unrealized": unreal, "realized_eq": s["eq"],
            "stats": {"wins": s["wins"], "losses": s["losses"], "win_rate": round(s["wins"] / n * 100, 1) if n else 0.0,
                      "profit_factor": round(s["gross_win"] / s["gross_loss"], 2) if s["gross_loss"] > 0 else 0.0,
                      "max_dd_pct": round(s["max_dd"] * 100, 2), "trades_today": s["trades_today"],
                      "daily_pnl_pct": round((eq_now / s["day_start"] - 1) * 100, 2) if s["day_start"] else 0.0},
        }

    # ------------------------------------------------------------ persistência
    def dump(self):
        return {"st": self.st}

    def restore(self, data):
        try:
            st = data.get("st", {})
            base = new_state()
            base.update({k: v for k, v in st.items() if k in base})
            for a in L.ASSETS:
                base["cooldown"].setdefault(a, 0)
                base["markers"].setdefault(a, [])
            self.st = base
            return True
        except Exception:
            return False

    async def close(self):
        for obj in (self.ex, self._session):
            if obj is not None:
                try:
                    await obj.close()
                except Exception:
                    pass
        self.ex, self._session = None, None
