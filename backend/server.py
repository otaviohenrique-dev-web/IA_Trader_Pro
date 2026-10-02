import asyncio
import copy
import csv
import hmac
import io
import json
import math
import os
import re
import time
import warnings
from contextlib import asynccontextmanager

import aiohttp
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

import live_model as L
from engine import KILL_SWITCH_DD, MODELS_DIR, POLL_SECONDS, STARTING_BALANCE, Engine

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
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")
CRYPTOCOMPARE_KEY = os.environ.get("CRYPTOCOMPARE_API_KEY") or os.environ.get("CRYPTOCOMPARE_KEY") or ""
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
STATE_FILE = os.environ.get("STATE_FILE", "data/live_state.json")
STATE_KEY = "ia_trader_pro:state:v2"

if not GEMINI_KEY:
    print(">>> ⚠️ GEMINI_API_KEY ausente: Sentinela de notícias opera em modo técnico.")
if not ADMIN_PASS:
    print(">>> ⚠️ ADMIN_PASSWORD ausente: endpoints administrativos ficam BLOQUEADOS.")


# --- ALERTAS (Telegram) ---
async def _send_telegram(text):
    """Envia ao Telegram. Retorna (ok, detalhe); o detalhe nunca contém o token."""
    if not (TG_TOKEN and TG_CHAT):
        return False, "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID não configurados no servidor"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as sess:
            async with sess.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT, "text": text}) as r:
                if r.status == 200:
                    return True, ""
                try:
                    desc = (await r.json()).get("description", "")
                except Exception:
                    desc = ""
                return False, f"Telegram respondeu HTTP {r.status}: {desc}"
    except Exception as e:
        print(f">>> ⚠️ Telegram indisponível: {type(e).__name__}")
        return False, f"falha de rede ({type(e).__name__})"


def notify(text):
    """Alerta no Telegram (silencioso se não configurado ou fora do loop de eventos)."""
    try:
        asyncio.get_running_loop().create_task(_send_telegram(text))
    except RuntimeError:
        pass


# --- ESTADO PÚBLICO ---
state = {
    "is_online": True, "started_at": time.time(), "uptime": "00:00:00", "status": "Reiniciando o sistema...",
    "starting_balance": STARTING_BALANCE, "balance": STARTING_BALANCE, "display_balance": STARTING_BALANCE, "floating_pnl": 0.0,
    "portfolio": {}, "markers": {}, "order_book": [],
    "adaptation": {"generation": 0, "wins": 0, "losses": 0, "current_win_rate": 0.0},
    "model": {"name": "", "loaded": False, "paper_trading": True},
    "news_agent": {"status": "INICIALIZANDO...", "sentiment_score": 0.0, "risk_level": "BAIXO",
                   "reason": "Aguardando primeira leitura do mercado...", "last_headlines": [], "mode": "observação"},
    "risk": {},
}
engine = Engine(notify, lambda: state["news_agent"]["status"])
global_safe_state_str = '{"status": "Aguardando sincronização..."}'


def refresh_state():
    global global_safe_state_str
    try:
        pub = engine.public()
        st, cfg = engine.st, engine.cfg or {}
        m = re.search(r"gen_(\d+)", engine.pkg or "")
        state.update({
            "status": pub["headline"], "balance": st["eq"], "display_balance": pub["equity"], "floating_pnl": pub["unrealized"],
            "portfolio": pub, "markers": st["markers"], "order_book": st["order_book"][:60],
        })
        state["model"] = {"name": engine.pkg or "", "loaded": engine.loaded, "paper_trading": True, "thr": cfg.get("thr"),
                          "status": cfg.get("status", ""), "selftest": engine.selftest, "source": engine.ex_name}
        state["adaptation"] = {"generation": int(m.group(1)) if m else 0, **{k: pub["stats"][k] for k in ("wins", "losses")},
                               "current_win_rate": pub["stats"]["win_rate"]}
        state["risk"] = {
            "trades_today": pub["stats"]["trades_today"], "max_trades_per_day": L.CFG["max_trades_day"],
            "daily_pnl_pct": pub["stats"]["daily_pnl_pct"], "daily_loss_limit_pct": L.CFG["daily_loss"] * 100,
            "max_drawdown_pct": pub["stats"]["max_dd_pct"], "profit_factor": pub["stats"]["profit_factor"],
            "entries_blocked": engine.block_reason() if engine.loaded else "", "halted": st["halted"],
            "kill_switch_pct": KILL_SWITCH_DD * 100, "risk_per_trade_pct": cfg.get("risk", 0) * 100,
            "max_positions": L.CFG["max_pos"], "open_positions": len(st["positions"]),
        }
        safe = clean_nans(copy.deepcopy(state))
        global_safe_state_str = json.dumps(safe)
    except Exception as e:
        print(f">>> ❌ Erro ao montar o estado: {type(e).__name__}: {e}")


# --- PERSISTÊNCIA (Render free tem disco efêmero: use Upstash Redis p/ sobreviver a reinícios) ---
async def persist_save():
    payload = json.dumps(clean_nans(engine.dump()))
    try:
        if UPSTASH_URL and UPSTASH_TOKEN:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                await s.post(UPSTASH_URL, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, json=["SET", STATE_KEY, payload])
        else:
            os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
            with open(STATE_FILE, "w") as f:
                f.write(payload)
        engine.dirty = False
    except Exception as e:
        print(f">>> ⚠️ Falha ao persistir estado: {e}")


async def persist_load():
    raw = None
    try:
        if UPSTASH_URL and UPSTASH_TOKEN:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
                async with s.post(UPSTASH_URL, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, json=["GET", STATE_KEY]) as resp:
                    raw = (await resp.json()).get("result")
        elif os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                raw = f.read()
        if raw and engine.restore(json.loads(raw)):
            print(f">>> 💾 Estado restaurado: patrimônio US$ {engine.st['eq']:.2f}, {len(engine.st['positions'])} posição(ões)")
    except Exception as e:
        print(f">>> ⚠️ Não foi possível restaurar o estado: {e}")


# --- SENTINELA DE NOTÍCIAS (modo observação: informa, não bloqueia) ---
try:
    from google import genai
    client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
except Exception:
    client = None

_NEWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
last_analysis_time = 0
cached_analysis = {"score": 0.1, "status": "SAFE", "reason": "Sincronizando com a rede neural (cache)..."}


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
    print(">>> 🕵️ IA_ANALISTA: Iniciando Sentinela de Mercado (modo observação)...")
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
            na = state["news_agent"]
            na["mode"] = "observação"
            if na["status"] in ("CAUTION", "DANGER"):
                engine.st["news_events"] = (engine.st["news_events"] + [{"ts": int(time.time()), "status": na["status"],
                                                                         "score": na["sentiment_score"]}])[-100:]
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f">>> ⚠️ Sentinela: {e}")
            await asyncio.sleep(60)


# --- LOOP DO MOTOR ---
async def engine_loop():
    await persist_load()
    ok, msg = await asyncio.to_thread(engine.load_package)
    print(f">>> 🧠 Pacote: {engine.pkg}" if ok else f">>> ⏳ Sem modelo: {msg}")
    last_save = time.time()
    while True:
        try:
            await engine.tick()
            if engine.dirty or time.time() - last_save > 300:
                await persist_save()
                last_save = time.time()
            refresh_state()
            await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            engine.last_error = f"{type(e).__name__}: {e}"
            print(f">>> ❌ Erro no ciclo do motor: {engine.last_error}")
            if any(w in str(e).lower() for w in ("ssl", "closed", "connection", "timeout", "network")):
                await engine.close()
                engine.ex = None
            refresh_state()
            await asyncio.sleep(10)


# --- FASTAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async def heartbeat():
        while True:
            state["uptime"] = time.strftime('%H:%M:%S', time.gmtime(int(time.time() - state["started_at"])))
            refresh_state()
            await asyncio.sleep(1.0)

    tasks = [asyncio.create_task(c) for c in (heartbeat(), engine_loop(), analyst_market_loop())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await persist_save()
        await engine.close()


app = FastAPI(lifespan=lifespan)
_origins = [o.strip().rstrip("/") for o in os.environ.get("FRONTEND_URL", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins,
                   allow_origin_regex=r"https://[a-zA-Z0-9-]+\.vercel\.app|http://localhost:\d+",
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])


def require_admin(password):
    if not ADMIN_PASS or not password or not hmac.compare_digest(password.encode(), ADMIN_PASS.encode()):
        raise HTTPException(status_code=401, detail="Acesso Negado.")


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": engine.loaded, "uptime": state["uptime"], "source": engine.ex_name,
            "selftest": engine.selftest["ok"]}


@app.get("/ready")
async def readiness_probe():
    ok = engine.loaded and engine.ready_bars
    return Response(content=json.dumps({"ready": ok, "model": engine.pkg}), media_type="application/json", status_code=200 if ok else 503)


@app.get("/api/state")
async def get_state_snapshot():
    return Response(content=global_safe_state_str, media_type="application/json")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_text(global_safe_state_str)
            await asyncio.sleep(1)
    except (WebSocketDisconnect, Exception):
        pass


@app.get("/api/historico")
async def get_historico(asset: str = "BTC", limit: int = 500):
    """Velas de 4H FECHADAS do par (a vela em formação chega pelo estado ao vivo)."""
    df = engine.bars.get(asset.upper())
    if df is None or df.empty:
        return []
    d = df.tail(max(10, min(limit, 1500)))
    return [{"time": int(r.timestamp // 1000), "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close)}
            for r in d.itertuples()]


@app.get("/api/download-dados")
async def download_dados(x_admin_password: str = Header(None)):
    require_admin(x_admin_password)
    log = engine.st.get("trade_log", [])
    if not log:
        raise HTTPException(status_code=404, detail="Nenhuma operação ainda.")
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=log[0].keys())
    w.writeheader()
    w.writerows(log)
    out.seek(0)
    return StreamingResponse(out, media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=operacoes_{int(time.time())}.csv"})


@app.post("/api/upload-cerebro")
async def upload_cerebro(file: UploadFile = File(...), x_admin_password: str = Header(None)):
    """Aceita o par gen_N.onnx + gen_N.json (envie os dois). O modelo só entra em uso se o par for válido e coerente.
    Atenção: no plano free o disco é apagado em reinícios; para ficar de vez, coloque os arquivos no repositório."""
    require_admin(x_admin_password)
    name = os.path.basename(file.filename or "")
    m = re.fullmatch(r"gen_(\d+)\.(onnx|json)", name)
    if not m:
        raise HTTPException(status_code=400, detail="Envie gen_N.onnx e gen_N.json (ex.: gen_1.onnx e gen_1.json).")
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Arquivo grande demais (máx 25MB).")
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(os.path.join(MODELS_DIR, name), "wb") as f:
        f.write(content)
    base = os.path.join(MODELS_DIR, f"gen_{m.group(1)}")
    if not (os.path.exists(base + ".onnx") and os.path.exists(base + ".json")):
        return {"status": "recebido", "arquivo": name, "falta": "envie também o outro arquivo do par"}
    ok, msg = await asyncio.to_thread(engine.load_package, base)
    if not ok:
        raise HTTPException(status_code=422, detail=msg)
    return {"status": "sucesso", "modelo": engine.pkg}


@app.post("/api/test-alert")
async def test_alert(x_admin_password: str = Header(None)):
    """Envia uma mensagem de teste ao Telegram (usa as variáveis guardadas no servidor)."""
    require_admin(x_admin_password)
    ok, detail = await _send_telegram("✅ Teste de alerta do IA Trader Pro: o Telegram está funcionando.")
    return {"enviado": ok, "detalhe": detail}


@app.post("/api/resume")
async def resume(x_admin_password: str = Header(None)):
    """Reativa o robô depois do kill-switch (o pico é redefinido para o patrimônio atual)."""
    require_admin(x_admin_password)
    engine.resume()
    await persist_save()
    refresh_state()
    notify("▶️ Robô reativado manualmente.")
    return {"status": "reativado", "patrimonio": engine.mtm()[0]}


@app.get("/api/shadow-report")
async def shadow_report():
    """Mede se o Analista de Notícias agregaria valor: resultado dos trades por status no momento da entrada."""
    groups = {}
    for t in engine.st["trade_log"]:
        g = groups.setdefault(t["news"], {"trades": 0, "ganhos": 0, "pnl_liquido": 0.0})
        g["trades"] += 1
        g["ganhos"] += int(t["net"] > 0)
        g["pnl_liquido"] = round(g["pnl_liquido"] + t["net"], 4)
    return {"modo": "observação (não bloqueia entradas)", "leituras_de_atencao_ou_perigo": len(engine.st["news_events"]),
            "trades_por_status_do_analista": groups, "ultimas_leituras": engine.st["news_events"][-10:]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 10000)),
                log_level="warning", access_log=False, proxy_headers=True, forwarded_allow_ips="*")
