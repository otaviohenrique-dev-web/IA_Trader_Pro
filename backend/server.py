import asyncio
import copy
import csv
import gc
import glob
import hmac
import io
import json
import math
import os
import re
import time
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiohttp
import ccxt.async_support as ccxt
import numpy as np
import onnxruntime as ort
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

import features as F

warnings.filterwarnings("ignore")
load_dotenv()


def clean_nans(obj):
    """Remove NaN/Inf e tipos numpy para o JSON não quebrar no navegador."""
    if isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_nans(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return 0.0 if math.isnan(obj) or math.isinf(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return clean_nans(obj.tolist())
    return obj


# --- CONFIGURAÇÃO ---
SYMBOL = 'BTC/USDT'
TIMEFRAME = '15m'
MODELS_DIR = "models"
POLL_SECONDS = 30                       # consulta preço/stop; a rede só decide 1x por vela fechada
WARMUP_BARS = 96                        # velas reprocessadas para aquecer a memória da LSTM
CONF_THRESHOLD = float(os.environ.get("CONF_THRESHOLD", 0.5))
DAILY_LOSS_LIMIT = float(os.environ.get("DAILY_LOSS_LIMIT", -0.03))   # bloqueia novas entradas no dia
STARTING_BALANCE = 100.0
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

CRYPTOCOMPARE_KEY = os.environ.get("CRYPTOCOMPARE_API_KEY") or os.environ.get("CRYPTOCOMPARE_KEY") or ""
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
STATE_FILE = os.environ.get("STATE_FILE", "data/live_state.json")
STATE_KEY = "ia_trader_pro:state"

if not GEMINI_KEY:
    print(">>> ⚠️ GEMINI_API_KEY ausente: Sentinela de notícias opera em modo técnico.")
if not ADMIN_PASS:
    print(">>> ⚠️ ADMIN_PASSWORD ausente: endpoints administrativos ficam BLOQUEADOS.")


def rotulo_risco_analista(codigo: str) -> str:
    return {"SAFE": "seguro", "CAUTION": "atenção", "DANGER": "perigo", "MODO TÉCNICO": "modo técnico"}.get(codigo, codigo)


def find_latest_model():
    """MODEL_PATH do ambiente, senão a maior geração disponível em models/."""
    env_path = os.environ.get("MODEL_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    paths = glob.glob(os.path.join(MODELS_DIR, "sniper_pro_gen_*.onnx"))
    key = lambda p: int(m.group(1)) if (m := re.search(r"gen_(\d+)", p)) else -1
    return max(paths, key=key) if paths else None


MODEL_PATH = find_latest_model()

# --- ESTADO DE TRADING (persistido) ---
tr = {
    "balance": STARTING_BALANCE, "position": 0, "entry_price": 0.0, "trade_start_balance": STARTING_BALANCE,
    "wins": 0, "losses": 0, "gross_win": 0.0, "gross_loss": 0.0,
    "cooldown": 0, "day": "", "day_start_balance": STARTING_BALANCE, "trades_today": 0,
    "peak": STARTING_BALANCE, "max_dd": 0.0, "last_bar_ts": 0,
}

state = {
    "asset": SYMBOL, "is_online": True, "in_position": False, "entry_price": 0.0, "current_position": 0,
    "balance": STARTING_BALANCE, "floating_pnl": 0.0, "display_balance": STARTING_BALANCE,
    "status": "Reiniciando o sistema...", "started_at": time.time(), "uptime": "00:00:00",
    "last_candle": {}, "chart_data": [], "markers": [], "order_book": [],
    "adaptation": {"generation": 1, "learning_state": "SISTEMA REINICIADO", "initial_win_rate": 0.0,
                   "current_win_rate": 0.0, "wins": 0, "losses": 0},
    "news_agent": {"status": "INICIALIZANDO...", "sentiment_score": 0.0, "risk_level": "BAIXO",
                   "reason": "Aguardando primeira leitura do mercado...", "last_headlines": []},
    "risk": {"trades_today": 0, "daily_pnl_pct": 0.0, "max_drawdown_pct": 0.0, "profit_factor": 0.0,
             "confidence": 0.0, "conf_threshold": CONF_THRESHOLD, "entries_blocked": ""},
    "performance": {"loop_avg_ms": 0.0, "loop_max_ms": 0.0, "healthy": True, "status": "OK"},
}

onnx_session = None
norm_stats = None
exchange = None
lstm_states = None
feat_row = {}                  # últimos indicadores (para o painel)
last_analysis_time = 0
cached_analysis = {"score": 0.1, "status": "SAFE", "reason": "Sincronizando com a rede neural (cache)..."}
global_safe_state_str = '{"status": "Aguardando sincronização neural..."}'
persist_dirty = False


def update_safe_state():
    global global_safe_state_str
    try:
        safe = clean_nans(copy.deepcopy(state))
        safe["markers"] = safe["markers"][-60:]
        safe["order_book"] = safe["order_book"][:60]
        global_safe_state_str = json.dumps(safe)
    except Exception as e:
        print(f">>> ❌ Erro ao sanitizar estado: {e}")


# --- PERSISTÊNCIA (Render free tem disco efêmero: use Upstash Redis p/ sobreviver a reinícios) ---
async def persist_save():
    global persist_dirty
    payload = json.dumps(clean_nans({"tr": tr, "markers": state["markers"][-60:],
                                     "order_book": state["order_book"][:60]}))
    try:
        if UPSTASH_URL and UPSTASH_TOKEN:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                await s.post(UPSTASH_URL, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                             json=["SET", STATE_KEY, payload])
        else:
            os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
            with open(STATE_FILE, "w") as f:
                f.write(payload)
        persist_dirty = False
    except Exception as e:
        print(f">>> ⚠️ Falha ao persistir estado: {e}")


async def persist_load():
    raw = None
    try:
        if UPSTASH_URL and UPSTASH_TOKEN:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.post(UPSTASH_URL, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                                  json=["GET", STATE_KEY]) as resp:
                    raw = (await resp.json()).get("result")
        elif os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                raw = f.read()
        if raw:
            data = json.loads(raw)
            tr.update({k: v for k, v in data.get("tr", {}).items() if k in tr})
            state["markers"] = data.get("markers", [])
            state["order_book"] = data.get("order_book", [])
            print(f">>> 💾 Estado restaurado: saldo US$ {tr['balance']:.2f}, posição {tr['position']}")
    except Exception as e:
        print(f">>> ⚠️ Não foi possível restaurar o estado: {e}")
    sync_public_state()


def sync_public_state():
    n = tr["wins"] + tr["losses"]
    state["balance"] = tr["balance"]
    state["in_position"] = tr["position"] != 0
    state["current_position"] = tr["position"]
    state["entry_price"] = tr["entry_price"]
    state["adaptation"].update({
        "wins": tr["wins"], "losses": tr["losses"],
        "current_win_rate": round(tr["wins"] / n * 100, 1) if n else 0.0})
    day_pnl = tr["balance"] / tr["day_start_balance"] - 1 if tr["day_start_balance"] else 0.0
    state["risk"].update({
        "trades_today": tr["trades_today"], "daily_pnl_pct": round(day_pnl * 100, 2),
        "max_drawdown_pct": round(tr["max_dd"] * 100, 2),
        "profit_factor": round(tr["gross_win"] / tr["gross_loss"], 2) if tr["gross_loss"] > 0 else 0.0})


# --- MOTOR ONNX ---
def load_brain(path=None):
    """Carrega modelo + estatísticas de normalização pareadas. Só substitui o atual se tudo estiver válido."""
    global onnx_session, norm_stats, lstm_states, MODEL_PATH
    path = path or MODEL_PATH
    if not path or not os.path.exists(path):
        print(f">>> ⚠️ Modelo ONNX não encontrado ({path}).")
        return False
    try:
        stats = F.load_stats(F.stats_path_for(path))
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        sess = ort.InferenceSession(path, sess_options=opts, providers=['CPUExecutionProvider'])
        if sess.get_inputs()[0].shape[1] != F.OBS_DIM or len(sess.get_outputs()) != 3:
            raise ValueError(f"modelo incompatível (esperado obs={F.OBS_DIM} e saídas logits+h+c)")
        onnx_session, norm_stats, lstm_states, MODEL_PATH = sess, stats, None, path
        print(f">>> ✅ Motor ONNX pronto: {path}")
        return True
    except Exception as e:
        print(f">>> ❌ Não foi possível carregar {path}: {e}")
        return False
    finally:
        gc.collect()


def run_brain(obs_vec):
    """Um passo da rede, avançando a memória da LSTM (chamar UMA vez por vela fechada)."""
    global lstm_states
    shape = onnx_session.get_inputs()[1].shape
    if lstm_states is None:
        h = np.zeros((shape[0], 1, shape[2]), np.float32)
        lstm_states = (h, h.copy())
    logits, h, c = onnx_session.run(None, {"obs": obs_vec.reshape(1, -1).astype(np.float32),
                                           "lstm_states_h": lstm_states[0], "lstm_states_c": lstm_states[1]})
    lstm_states = (h, c)
    return logits[0]


# --- SENTINELA DE NOTÍCIAS ---
try:
    from google import genai
    client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
except Exception:
    client = None

_NEWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


async def _cryptocompare_news_titles(session, query: str) -> list:
    key_q = f"&api_key={CRYPTOCOMPARE_KEY}" if CRYPTOCOMPARE_KEY else ""
    url = f"https://min-api.cryptocompare.com/data/v2/news/?{query}{key_q}"
    async with session.get(url, headers={"User-Agent": _NEWS_UA}) as resp:
        if resp.status == 200:
            data = await resp.json()
            return [f" {p['title']} •" for p in data.get("Data", [])[:10]]
        if resp.status == 429:
            return ["API_ESGOTADA"]
        return []


async def fetch_btc_news():
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            for q in ("categories=BTC&lang=PT", "categories=BTC&lang=EN"):
                titles = await _cryptocompare_news_titles(session, q)
                if titles:
                    return titles
    except Exception:
        pass
    return []


async def analyze_sentiment_with_llm(headlines):
    global last_analysis_time, cached_analysis
    now = time.time()
    if now - last_analysis_time < 3600:
        return cached_analysis
    if not headlines:
        return {"score": 0.1, "status": "SAFE", "reason": "Mercado calmo (sem notícias)"}
    if not client:
        return {"score": 0.1, "status": "SAFE", "reason": "Cliente IA indisponível - modo técnico"}

    prompt = f"""
    Você é um Gestor de Risco Quantitativo sênior de Bitcoin. Avalie o risco macroeconômico atual baseado nestas manchetes (em português ou inglês):
    {headlines}

    REGULAGEM DE RISCO ESTREITA:
    - Score 0.0 a 0.60 (SAFE): Notícias de adoção, ETFs, desenvolvimentos técnicos, ou FUD genérico.
    - Score 0.61 a 0.80 (CAUTION): Notícias macroeconômicas ruins REAIS (ex: aumento severo de juros).
    - Score 0.81 a 1.0 (DANGER): Eventos catastróficos globais, falência de corretoras.

    Responda APENAS em JSON puro: {{"score": float, "status": "SAFE" ou "CAUTION" ou "DANGER", "reason": "resumo de 1 linha do sentimento geral"}}
    """
    try:
        resp = await asyncio.to_thread(client.models.generate_content, model=GEMINI_MODEL, contents=prompt)
        txt = resp.text
        data = json.loads(txt[txt.index('{'): txt.rindex('}') + 1])
        score = float(data.get("score", 0.0))
        if score > 1.0:
            score = score / 10.0 if score <= 10.0 else 1.0
        data["score"] = score
        data["status"] = "SAFE" if score <= 0.60 else ("CAUTION" if score <= 0.80 else "DANGER")
        cached_analysis, last_analysis_time = data, now
        return data
    except Exception as e:
        print(f">>> ⚠️ Sentinela LLM falhou ({e}); mantendo cache.")
        return cached_analysis


async def analyst_market_loop():
    print(">>> 🕵️ IA_ANALISTA: Iniciando Sentinela de Mercado...")
    while True:
        try:
            headlines = await fetch_btc_news()
            if headlines and headlines[0] == "API_ESGOTADA":
                state["news_agent"].update({
                    "status": "SAFE", "sentiment_score": 0.0, "risk_level": "MODO TÉCNICO",
                    "reason": "Acesso a notícias bloqueado. IA operando apenas com Análise Técnica (Gráficos).",
                    "last_headlines": ["⚠️ ALERTA: API DE NOTÍCIAS ESGOTADA - TRABALHANDO 100% VIA GRÁFICOS (TA) •"]})
            else:
                a = await analyze_sentiment_with_llm(headlines)
                state["news_agent"].update({
                    "status": a["status"], "sentiment_score": a["score"], "risk_level": a["status"],
                    "reason": a.get("reason", "Análise concluída sem justificativa explícita."),
                    "last_headlines": headlines or ["SISTEMA EM MONITORAMENTO: AGUARDANDO NOVOS EVENTOS •"]})
            update_safe_state()
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f">>> ⚠️ Sentinela: {e}")
            await asyncio.sleep(60)


# --- NÚCLEO DE TRADING (paper trading: simula, não envia ordens à corretora) ---
def now_hms():
    return datetime.now().strftime('%H:%M:%S')


def _bar_time(ts_ms):
    return int(ts_ms // 1000)


def close_position(price, bar_ts_ms, reason):
    """Fecha a posição aberta: PnL bruto, taxa de saída e contabilidade."""
    pos = tr["position"]
    change = (price - tr["entry_price"]) / tr["entry_price"] if pos == 1 else (tr["entry_price"] - price) / tr["entry_price"]
    tr["balance"] += tr["balance"] * change
    tr["balance"] -= tr["balance"] * F.COST_PER_SIDE
    net = tr["balance"] - tr["trade_start_balance"]
    if net > 0:
        tr["wins"] += 1
        tr["gross_win"] += net
    else:
        tr["losses"] += 1
        tr["gross_loss"] += -net
    tr["position"], tr["entry_price"], tr["cooldown"] = 0, 0.0, F.COOLDOWN_BARS
    tr["peak"] = max(tr["peak"], tr["balance"])
    tr["max_dd"] = min(tr["max_dd"], tr["balance"] / tr["peak"] - 1)

    state["markers"].append({"time": _bar_time(bar_ts_ms), "position": "aboveBar", "color": "#facc15",
                             "shape": "square", "text": f"SAÍDA: {'GANHO' if net > 0 else 'PERDA'}"})
    lado = "compra (long)" if pos == 1 else "venda (short)"
    state["order_book"].insert(0, {"text": f"[{now_hms()}] 🏁 Fechou {lado} ({reason}) | PnL líquido: US$ {net:.2f} ({'ganho ✅' if net > 0 else 'perda ❌'})"})
    state["markers"] = state["markers"][-120:]
    state["order_book"] = state["order_book"][:120]


def open_position(side, price, bar_ts_ms):
    tr["trade_start_balance"] = tr["balance"]
    tr["balance"] -= tr["balance"] * F.COST_PER_SIDE
    tr["position"], tr["entry_price"] = side, price
    tr["trades_today"] += 1
    state["markers"].append({"time": _bar_time(bar_ts_ms), "position": "belowBar" if side == 1 else "aboveBar",
                             "color": "#22c55e" if side == 1 else "#ef4444", "shape": "circle",
                             "text": f"ENTRADA {'COMPRA' if side == 1 else 'VENDA'}"})
    lado = "compra (long)" if side == 1 else "venda (short)"
    state["order_book"].insert(0, {"text": f"[{now_hms()}] 🚀 Abriu {lado} a US$ {price:.2f} (custo: {F.COST_PER_SIDE*100:.3f}%)"})


def roll_day():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if tr["day"] != today:
        tr["day"], tr["day_start_balance"], tr["trades_today"] = today, tr["balance"], 0


def entry_block_reason():
    """Motivo pelo qual novas entradas estão proibidas agora ('' = liberado)."""
    if tr["balance"] / tr["day_start_balance"] - 1 <= DAILY_LOSS_LIMIT:
        return f"limite de perda diária ({DAILY_LOSS_LIMIT*100:.0f}%)"
    if state["news_agent"]["status"] in ("CAUTION", "DANGER"):
        return f"analista de notícias: {rotulo_risco_analista(state['news_agent']['status'])}"
    return ""


def build_live_features(closed_15m, closed_4h):
    cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    df = F.compute_features(pd.DataFrame(closed_15m, columns=cols), pd.DataFrame(closed_4h, columns=cols))
    return df, F.normalize(df, norm_stats)


def obs_with_position(x, price):
    pos = tr["position"]
    unreal = pos * (price / tr["entry_price"] - 1.0) / F.STOP_LOSS_PCT if pos != 0 else 0.0
    return np.concatenate([x, np.array([pos, np.clip(unreal, -2.0, 2.0)], np.float32)])


async def trading_tick():
    global feat_row, lstm_states
    stop_note = ""
    ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=720)
    if len(ohlcv) < 300:
        raise RuntimeError("histórico insuficiente da corretora")
    now_ms = int(time.time() * 1000)
    forming = ohlcv[-1] if ohlcv[-1][0] + F.M15_MS > now_ms else None
    closed = ohlcv[:-1] if forming else ohlcv
    live = forming or closed[-1]
    price = float(live[4])
    last_closed_ts = int(closed[-1][0])
    roll_day()

    # --- stop-loss / take-profit com o preço ao vivo (checado a cada POLL_SECONDS) ---
    if tr["position"] != 0:
        chg = tr["position"] * (price - tr["entry_price"]) / tr["entry_price"]
        if chg <= -F.STOP_LOSS_PCT or chg >= F.TAKE_PROFIT_PCT:
            close_position(price, live[0], "STOP-LOSS" if chg < 0 else "TAKE-PROFIT")
            stop_note = "🚨 STOP-LOSS ACIONADO" if chg < 0 else "🎯 ALVO ATINGIDO"
            sync_public_state()
            await persist_save()

    # --- decisão da rede: uma vez por vela FECHADA ---
    if last_closed_ts != tr["last_bar_ts"]:
        if onnx_session is not None and norm_stats is not None:
            ohlcv4 = await exchange.fetch_ohlcv(SYMBOL, timeframe='4h', limit=720)
            closed4 = [r for r in ohlcv4 if r[0] + F.H4_MS <= now_ms]
            df, X = await asyncio.to_thread(build_live_features, closed, closed4)
            row = df.iloc[-1]
            feat_row = {k: float(row[k]) for k in ('rsi', 'bb_width', 'ema50_4h', 'ema200_4h')}

            # aquece/atualiza a memória da LSTM com as velas que ela ainda não viu
            if lstm_states is None:
                backlog = range(max(0, len(df) - 1 - WARMUP_BARS), len(df) - 1)
            else:
                backlog = [i for i in range(len(df) - 1) if df['timestamp'].iat[i] > tr["last_bar_ts"]]
            for i in backlog:
                run_brain(obs_with_position(X[i], float(df['close'].iat[i])))

            tr["cooldown"] = max(0, tr["cooldown"] - 1)
            logits = run_brain(obs_with_position(X[-1], price))
            action, conf = F.pick_action(logits, tr["position"], CONF_THRESHOLD)
            target = F.resolve_target(tr["position"], action, tr["cooldown"], tr["trades_today"])
            state["risk"]["confidence"] = round(conf, 3)

            block = entry_block_reason()
            if target != 0 and tr["position"] == 0 and block:
                target = 0
            if target != tr["position"]:
                if tr["position"] != 0:
                    close_position(price, row['timestamp'], "sinal da IA")
                if target != 0:
                    open_position(target, price, row['timestamp'])
                await persist_save()
            tr["last_bar_ts"] = last_closed_ts
            sync_public_state()

    # --- status e painel ---
    if onnx_session is None or norm_stats is None:
        state["status"] = "⏳ MOTOR OFFLINE (sem modelo/estatísticas válidos)..."
    elif stop_note:
        state["status"] = stop_note
    elif tr["position"] != 0:
        state["status"] = "📊 MONITORANDO POSIÇÃO..."
    elif entry_block_reason():
        state["status"] = f"⏳ ENTRADA BLOQUEADA: {entry_block_reason()}"
    elif tr["cooldown"] > 0:
        state["status"] = f"🧊 COOLDOWN: {tr['cooldown']} vela(s)"
    else:
        state["status"] = "🔍 BUSCANDO OPORTUNIDADE..."

    floating = 0.0
    if tr["position"] != 0:
        floating = tr["balance"] * tr["position"] * (price - tr["entry_price"]) / tr["entry_price"]
    state["floating_pnl"] = floating
    state["display_balance"] = tr["balance"] + floating
    state["last_candle"] = {"time": _bar_time(live[0]), "open": live[1], "high": live[2], "low": live[3],
                            "close": live[4], **feat_row}
    sync_public_state()
    update_safe_state()


async def sniper_loop():
    global exchange
    await persist_load()
    state["status"] = "⚙️ Carregando Motor de Inferência..."
    await asyncio.to_thread(load_brain)
    state["adaptation"]["generation"] = int(m.group(1)) if MODEL_PATH and (m := re.search(r"gen_(\d+)", MODEL_PATH)) else 1
    exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
    last_save = time.time()

    while True:
        t0 = time.time()
        try:
            await trading_tick()
            ms = (time.time() - t0) * 1000
            perf = state["performance"]
            perf["loop_avg_ms"] = round(perf["loop_avg_ms"] * 0.9 + ms * 0.1, 1)
            perf["loop_max_ms"] = round(max(perf["loop_max_ms"], ms), 1)
            if time.time() - last_save > 300:
                await persist_save()
                last_save = time.time()
            await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f">>> ❌ Erro no ciclo de trading: {type(e).__name__}: {e}")
            state["status"] = "❌ Erro de conexão com a corretora (tentando novamente)"
            if any(w in str(e).lower() for w in ("ssl", "closed", "connectionreset")):
                try:
                    await exchange.close()
                except Exception:
                    pass
                exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
            await asyncio.sleep(10)


# --- FASTAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async def heartbeat():
        while True:
            state["uptime"] = time.strftime('%H:%M:%S', time.gmtime(int(time.time() - state["started_at"])))
            update_safe_state()
            await asyncio.sleep(2.0)

    tasks = [asyncio.create_task(c) for c in (heartbeat(), sniper_loop(), analyst_market_loop())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await persist_save()
        if exchange is not None:
            try:
                await exchange.close()
            except Exception:
                pass


app = FastAPI(lifespan=lifespan)
_origins = [o.strip() for o in os.environ.get("FRONTEND_URL", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])


def require_admin(password):
    if not ADMIN_PASS or not password or not hmac.compare_digest(password.encode(), ADMIN_PASS.encode()):
        raise HTTPException(status_code=401, detail="Acesso Negado.")


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": onnx_session is not None, "uptime": state["uptime"]}


@app.get("/ready")
async def readiness_probe():
    ok = onnx_session is not None
    return Response(content=json.dumps({"ready": ok, "model": MODEL_PATH}), media_type="application/json",
                    status_code=200 if ok else 503)


@app.get("/api/state")
async def get_state_snapshot():
    return Response(content=global_safe_state_str, media_type="application/json")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(global_safe_state_str)
            await asyncio.sleep(2)
    except (WebSocketDisconnect, Exception):
        pass


@app.get("/api/historico")
async def get_historico():
    """Velas de 15m (mesmo timeframe da vela ao vivo e dos marcadores do gráfico)."""
    try:
        ex = exchange or ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
        try:
            ohlcv = await ex.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=720)
        finally:
            if ex is not exchange:
                await ex.close()
        return [{"time": int(r[0] / 1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
    except Exception:
        return []


@app.get("/api/download-dados")
async def download_dados(x_admin_password: str = Header(None)):
    require_admin(x_admin_password)
    markers = state.get('markers', [])
    if not markers:
        raise HTTPException(status_code=404, detail="Nenhum dado.")
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=markers[0].keys())
    w.writeheader()
    w.writerows(markers)
    out.seek(0)
    return StreamingResponse(out, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=live_market_data_{int(time.time())}.csv"})


@app.post("/api/upload-cerebro")
async def upload_cerebro(file: UploadFile = File(...), x_admin_password: str = Header(None)):
    """Aceita um .onnx e/ou o .stats.json pareado. Um modelo só entra em uso se carregar com as stats dele."""
    require_admin(x_admin_password)
    name = os.path.basename(file.filename or "")
    if not (name.endswith(".onnx") or name.endswith(".stats.json")):
        raise HTTPException(status_code=400, detail="Envie um .onnx ou o .stats.json correspondente.")
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Arquivo grande demais (máx 25MB).")
    os.makedirs(MODELS_DIR, exist_ok=True)
    dest = os.path.join(MODELS_DIR, name)
    with open(dest, "wb") as f:
        f.write(content)
    if name.endswith(".stats.json"):
        return {"status": "stats salvo", "arquivo": name}
    ok = await asyncio.to_thread(load_brain, dest)
    if not ok:
        raise HTTPException(status_code=422, detail="Modelo rejeitado (envie antes o .stats.json pareado, com o mesmo nome base).")
    state["adaptation"]["generation"] += 1
    state["adaptation"]["learning_state"] = f"COMPILADO INJETADO ({name})"
    return {"status": "sucesso"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 10000)),
                log_level="warning", access_log=False, proxy_headers=True, forwarded_allow_ips="*")
