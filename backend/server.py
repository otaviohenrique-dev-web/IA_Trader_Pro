import asyncio
import json
import time
import shutil
from datetime import datetime
import pandas as pd
import numpy as np
import pandas_ta_classic as ta
import ccxt.async_support as ccxt
from contextlib import asynccontextmanager
import os
import gc
import math
import copy
import torch
from sb3_contrib import RecurrentPPO
import warnings
import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Header
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
import io
import csv

warnings.filterwarnings("ignore")

# Trava o PyTorch para não estrangular a CPU do Render
torch.set_num_threads(1)

# --- SANITIZADOR UNIVERSAL (Elimina o veneno do NaN do Javascript) ---
def clean_nans(obj):
    if isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nans(v) for v in obj]
    elif isinstance(obj, float):
        return 0.0 if math.isnan(obj) or math.isinf(obj) else obj
    elif isinstance(obj, np.floating):
        return 0.0 if np.isnan(obj) or np.isinf(obj) else float(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return clean_nans(obj.tolist())
    return obj

# --- CONFIGURAÇÕES DO SISTEMA ---
SYMBOL = 'BTC/USDT'
TIMEFRAME = '15m' 
MODEL_PATH = "models/sniper_pro_gen_6.zip" 
START_TIME = time.time()
FEE_RATE = 0.0010 
STOP_LOSS_PCT = -0.010    
TAKE_PROFIT_PCT = +0.020 

# 1. Tenta carregar o arquivo .env que está na mesma pasta (backend/.env)
load_dotenv()

# 2. Puxa as variáveis (CryptoCompare: notícias BTC; Gemini: Sentinela)
CRYPTOCOMPARE_KEY = os.environ.get("CRYPTOCOMPARE_API_KEY") or os.environ.get("CRYPTOCOMPARE_KEY") or ""
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")

# 3. Avisos de configuração
if not GEMINI_KEY:
    print(">>> ⚠️ ALERTA CRÍTICO: GEMINI_API_KEY não encontrada no ambiente ou no .env!")
    print(">>> O Sentinela (análise de risco por LLM) pode falhar.")
if not CRYPTOCOMPARE_KEY:
    print(">>> ⚠️ AVISO: CRYPTOCOMPARE_API_KEY não encontrada. Cota de notícias pode ser menor.")

# --- VARIÁVEIS GLOBAIS DE ESTADO ---
balance = 100.00
position = 0 
entry_price = 0.0
wins = 0
losses = 0
DAILY_LOSS_LIMIT = -0.05  
session_start_balance = 100.0  
kill_switch_active = False
max_profit_pct = 0.0  

# Variáveis de Controle de Fluxo
startup_phase = True
startup_timer = 0
warming_up = True 
warmup_counter = 0
consecutive_signals = 0 
last_signal = 0   
last_entry_ts = 0

def rotulo_risco_analista(codigo: str) -> str:
    """Rótulos em português para o painel."""
    return {
        "SAFE": "seguro",
        "CAUTION": "atenção",
        "DANGER": "perigo",
        "MODO TÉCNICO": "modo técnico",
    }.get(codigo, codigo)

state = {
    "asset": SYMBOL,
    "is_online": True,
    "in_position": False,
    "entry_price": 0.0,
    "current_position": 0,
    "balance": balance, 
    "status": "Reiniciando o sistema...",
    "uptime": "00:00:00",
    "last_candle": {},
    "chart_data": [],
    "markers": [],
    "order_book": [], 
    "adaptation": {
        "generation": 1,
        "learning_state": "SISTEMA REINICIADO",
        "initial_win_rate": 0.0,
        "current_win_rate": 0.0,
        "wins": 0,      
        "losses": 0     
    },
    "news_agent": {
        "status": "INICIALIZANDO...",
        "sentiment_score": 0.0,
        "risk_level": "BAIXO",
        "last_headlines": []
    },
    "performance": {
        "loop_avg_ms": 0.0,
        "loop_max_ms": 0.0,
        "healthy": True,
        "status": "Inicializando..."
    }
}

model = None
exchange = None
lstm_states = None 
episode_starts = np.ones((1,), dtype=bool)
feature_cols = ['log_ret', 'rsi', 'rsi_slope', 'macd_diff', 'bb_pband', 'bb_width', 'dist_ema50', 'dist_ema200', 'atr_pct']
last_analysis_time = 0
cached_analysis = {"score": 50, "status": "SAFE", "reason": "Sincronizando com a rede neural (cache)..."}
# Cliente global para websockets
connected_clients = []

# --- CACHE DO ESTADO SANITIZADO (TICKET 3 + BLINDAGEM) ---
global_safe_state_str = '{"status": "Aguardando sincronização neural..."}'

def update_safe_state():
    """Sanitiza e empacota o estado APENAS quando ele sofre alterações."""
    global global_safe_state_str
    try:
        safe_state = clean_nans(copy.deepcopy(state))
        if safe_state.get("markers") and len(safe_state["markers"]) > 50:
            safe_state["markers"] = safe_state["markers"][-50:]
        if safe_state.get("order_book") and len(safe_state["order_book"]) > 30:
            safe_state["order_book"] = safe_state["order_book"][:30]
        global_safe_state_str = json.dumps(safe_state)
    except Exception as e:
        print(f">>> ❌ Erro ao sanitizar estado: {e}")

def run_startup_backtest(df_clean, model_instance):
    """Backtest rápido de inicialização - apenas primeira validação."""
    print(">>> 🔬 EXECUTANDO BACKTEST DE REBOOT...")
    if model_instance is None:
        return 50.0
    
    test_wins, test_losses = 0, 0
    sim_pos, sim_entry = 0, 0.0
    temp_lstm, temp_ep = None, np.ones((1,), dtype=bool)
    test_df = df_clean.tail(100)
    
    start_bt = time.time()
    max_bt_time = 3.0 
    
    for i in range(len(test_df)):
        if (time.time() - start_bt) > max_bt_time: break
        try:
            obs = test_df[feature_cols].iloc[i].values.astype(np.float32)
            action, temp_lstm = model_instance.predict(obs, state=temp_lstm, episode_start=temp_ep, deterministic=True)
            temp_ep = np.zeros((1,), dtype=bool)
            act_idx = action.item()
            target_pos = 1 if act_idx == 1 else (-1 if act_idx == 2 else 0)
            
            if target_pos != sim_pos:
                if sim_pos != 0:
                    chg = (test_df.iloc[i]['close'] - sim_entry) / sim_entry
                    pnl = chg if sim_pos == 1 else -chg
                    if pnl > 0: test_wins += 1
                    else: test_losses += 1
                if target_pos != 0: sim_entry = test_df.iloc[i]['close']
                sim_pos = target_pos
        except: continue
    
    tot = test_wins + test_losses
    win_rate = round((test_wins/tot)*100, 1) if tot > 0 else 50.0
    return win_rate

def load_brain(path=MODEL_PATH):
    """Carrega modelo de forma síncrona com otimização agressiva de RAM."""
    global model
    try:
        if os.path.exists(path):
            import zipfile
            if not zipfile.is_zipfile(path):
                print(f"❌ Arquivo {path} NÃO é um ZIP válido!")
                model = None
                return
            
            print(f">>> 🧠 Carregando modelo: {path}")
            gc.collect()
            model = RecurrentPPO.load(path, device="cpu")
            gc.collect()
            print(f">>> ✅ Modelo carregado com sucesso")
        else:
            model = None
    except Exception as e:
        print(f"❌ Erro ao carregar modelo: {e}")
        model = None
    finally:
        gc.collect()

def get_uptime():
    seconds = int(time.time() - START_TIME)
    return time.strftime('%H:%M:%S', time.gmtime(seconds))

# --- INICIALIZAÇÃO DO CLIENTE (SDK ATUALIZADO) ---
from google import genai
try:
    if GEMINI_KEY: client = genai.Client(api_key=GEMINI_KEY)
    else: client = genai.Client() 
except Exception as e:
    client = None

# --- AGENTE DE NOTÍCIAS (IA SENTINELA) ---
_NEWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def _cryptocompare_news_titles(session, query: str, headers: dict) -> list:
    key_q = f"&api_key={CRYPTOCOMPARE_KEY}" if CRYPTOCOMPARE_KEY else ""
    url = f"https://min-api.cryptocompare.com/data/v2/news/?{query}{key_q}"
    async with session.get(url, headers=headers, timeout=15) as resp:
        if resp.status == 200:
            data = await resp.json()
            results = data.get("Data", [])
            if results: return [f" {p['title']} •" for p in results[:10]]
            return []
        if resp.status == 429: return ["API_ESGOTADA"]
        return []

async def fetch_btc_news():
    headers = {"User-Agent": _NEWS_UA}
    try:
        async with aiohttp.ClientSession() as session:
            titles = await _cryptocompare_news_titles(session, "categories=BTC&lang=PT", headers)
            if titles and titles[0] == "API_ESGOTADA": return titles
            if not titles: titles = await _cryptocompare_news_titles(session, "categories=BTC&lang=EN", headers)
            return titles
    except: return []

async def analyst_market_loop():
    print(">>> 🕵️ IA_ANALISTA: Iniciando Sentinela de Mercado...")
    global kill_switch_active
    headers = {"User-Agent": _NEWS_UA}
    
    while True:
        try:
            headlines = await fetch_btc_news()
            if not headlines:
                async with aiohttp.ClientSession() as session:
                    for q in ("lang=PT", "lang=EN"):
                        headlines = await _cryptocompare_news_titles(session, q, headers)
                        if headlines: break

            if headlines and headlines[0] == "API_ESGOTADA":
                state["news_agent"].update({
                    "status": "SAFE",
                    "sentiment_score": 0.0,
                    "risk_level": "MODO TÉCNICO",
                    "last_headlines": ["⚠️ ALERTA: API DE NOTÍCIAS ESGOTADA - TRABALHANDO 100% VIA GRÁFICOS (TA) •"]
                })
                kill_switch_active = False
                await asyncio.sleep(3600)
                continue

            analysis = await analyze_sentiment_with_llm(headlines)
            state["news_agent"].update({
                "status": analysis["status"],
                "sentiment_score": analysis["score"],
                "risk_level": analysis["status"],
                "last_headlines": headlines if headlines else ["SISTEMA EM MONITORAMENTO: AGUARDANDO NOVOS EVENTOS •"]
            })
            
            if analysis["status"] == "SAFE": kill_switch_active = False
            update_safe_state() 
            await asyncio.sleep(3600) 
            
        except Exception as e:
            await asyncio.sleep(60)

async def analyze_sentiment_with_llm(headlines):
    global last_analysis_time, cached_analysis
    current_time = time.time()
    
    if current_time - last_analysis_time < 3600: return cached_analysis
    if not headlines: return {"score": 0.1, "status": "SAFE", "reason": "Mercado calmo (Sem notícias)"}
    if not client: return {"score": 0.1, "status": "SAFE", "reason": "Cliente IA indisponível - modo técnico"}
    
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
        response = await asyncio.to_thread(client.models.generate_content, model="gemini-3-flash-preview", contents=prompt)
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_text)
        score = float(data.get("score", 0.0))
        if score > 1.0: score = score / 10.0 if score <= 10.0 else 1.0
        
        data["status"] = "SAFE" if score <= 0.60 else ("CAUTION" if score <= 0.80 else "DANGER")
        data["score"] = score
        cached_analysis = data
        last_analysis_time = current_time
        return data
        
    except Exception as e:
        return cached_analysis

# --- LOOP PRINCIPAL DO TRADER (SNIPER) ---
async def sniper_loop():
    global state, exchange, lstm_states, episode_starts, balance, position, entry_price, wins, losses
    global kill_switch_active, last_entry_ts, startup_phase, startup_timer, warming_up, warmup_counter, consecutive_signals, last_signal

    try:
        exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
    except Exception as e:
        await asyncio.sleep(5)
        return

    state["status"] = "Sistema iniciando... (conectado à corretora)"
    last_fetch_ts = 0
    lstm_states = None
    episode_starts = np.ones((1,), dtype=bool)
    consecutive_signals = 0
    last_signal = 0

    model_wait_start = time.time()
    while model is None and (time.time() - model_wait_start) < 10:
        state["status"] = f"🧠 Inicializando Rede Neural... ({int(time.time() - model_wait_start)}s)"
        await asyncio.sleep(0.5)
    
    if model is not None: await asyncio.sleep(0.1)

    loop_counter = 0 
    
    while True:
        loop_counter += 1
        try:
            now_ts = time.time()
            if now_ts - last_fetch_ts > 60 or last_fetch_ts == 0:
                try:
                    ohlcv = await asyncio.wait_for(exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=250), timeout=15.0)
                    
                    def process_indicators(ohlcv_data):
                        df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                        df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
                        df['rsi'] = ta.rsi(df['close'], length=14)
                        df['rsi_slope'] = df['rsi'].diff()
                        
                        macd = ta.macd(df['close'])
                        if macd is not None and not macd.empty:
                            macd_col = [c for c in macd.columns if c.startswith('MACDh') or c.startswith('MACDH')][0]
                            df['macd_diff'] = macd[macd_col]
                        else: df['macd_diff'] = 0.0
                        
                        bb = ta.bbands(df['close'], length=20, std=2)
                        if bb is not None and not bb.empty:
                            upper_col = [c for c in bb.columns if c.startswith('BBU')][0]
                            lower_col = [c for c in bb.columns if c.startswith('BBL')][0]
                            width_col = [c for c in bb.columns if c.startswith('BBB')][0]
                            df['bb_pband'] = (df['close'] - bb[lower_col]) / (bb[upper_col] - bb[lower_col])
                            df['bb_width'] = bb[width_col]
                        else: df['bb_pband'], df['bb_width'] = 0.0, 0.0
                        
                        df['ema50'] = ta.ema(df['close'], length=50)
                        df['ema200'] = ta.ema(df['close'], length=200)
                        df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
                        df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
                        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                        df['atr_pct'] = df['atr'] / df['close']
                        
                        return df, df.dropna().copy()
                    
                    df, df_clean = await asyncio.to_thread(process_indicators, ohlcv)
                    last_fetch_ts = now_ts
                except Exception as e:
                    state["status"] = "❌ Erro conexão API"
                    await asyncio.sleep(2)
                    continue

            if 'df_clean' in locals() and len(df_clean) > 0:
                last_row = df_clean.iloc[-1]
                current_price = float(last_row['close'])
                target_pos = position 

                floating_pnl = 0.0
                if position != 0:
                    change_pct = (current_price - entry_price) / entry_price if position == 1 else (entry_price - current_price) / entry_price
                    floating_pnl = balance * change_pct
                
                state["floating_pnl"] = floating_pnl
                state["display_balance"] = balance + floating_pnl

                if startup_phase:
                    if model is None:
                        state["status"] = "⏳ Aguardando modelo para backtest..."
                        await asyncio.sleep(0.5)
                        continue 
                    
                    state["status"] = "Reinício: executando backtest..."
                    startup_timer += 1
                    if startup_timer == 1:
                        res = await asyncio.to_thread(run_startup_backtest, df_clean, model)
                        state["adaptation"]["initial_win_rate"] = res
                        state["adaptation"]["current_win_rate"] = res
                    if startup_timer > 2: 
                        startup_phase = False
                        lstm_states = None 
                elif warming_up:
                    warmup_counter += 1
                    state["status"] = f"🛡️ AQUECIMENTO... ({warmup_counter}/15)"
                    if warmup_counter >= 15:
                        warming_up = False
                        state["status"] = "📊 AGUARDANDO SINAL..."
                else:
                    if model is not None:
                        try:
                            obs = last_row[feature_cols].values.astype(np.float32)
                            action, lstm_states = await asyncio.to_thread(
                                model.predict, obs, state=lstm_states, episode_start=episode_starts, deterministic=True
                            )
                            episode_starts = np.zeros((1,), dtype=bool)
                            act_idx = action.item()
                        except:
                            act_idx = 0
                            episode_starts = np.ones((1,), dtype=bool)
                    else:
                        act_idx = 0
                        state["status"] = "⏳ MODELO CARREGANDO... (aguardando)"

                    if act_idx != 0 and act_idx == last_signal: consecutive_signals += 1
                    elif act_idx != 0: consecutive_signals = 1; last_signal = act_idx
                    else: consecutive_signals = 0; last_signal = 0

                    if position != 0:
                        remaining = 900 - (int(time.time()) - last_entry_ts)
                        if remaining > 0:
                            target_pos = position
                            state["status"] = f"PROTEÇÃO: {remaining}s"
                        else:
                            state["status"] = "📊 MONITORANDO MERCADO..."
                            if act_idx == 0: target_pos = 0
                    elif position == 0:
                        is_safe = state["news_agent"]["status"] == "SAFE"
                        if not is_safe:
                            state["status"] = f"⏳ AGUARDANDO ANALISTA ({rotulo_risco_analista(state['news_agent']['status'])})"
                        elif consecutive_signals >= 3:
                            target_pos = 1 if act_idx == 1 else (-1 if act_idx == 2 else 0)
                        else:
                            state["status"] = "🔍 BUSCANDO OPORTUNIDADE..."

                if target_pos != position:
                    if position != 0:
                        pnl = (balance * ((current_price - entry_price)/entry_price)) if position == 1 else (balance * -((current_price - entry_price)/entry_price))
                        balance += (pnl - (balance * FEE_RATE))
                        
                        state["markers"].append({
                            "time": int(last_row['timestamp'].timestamp()), "position": "aboveBar",
                            "color": "#facc15", "shape": "square", "text": f"SAÍDA: {'GANHO' if pnl > 0 else 'PERDA'}"
                        })
                        
                        resultado_texto = "ganho ✅" if pnl > 0 else "perda ❌"
                        lado = "compra (long)" if position == 1 else "venda (short)"
                        state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🏁 Fechou {lado} | PnL: US$ {pnl:.2f} ({resultado_texto})"})
                        
                        state["balance"] = balance
                        state["floating_pnl"] = 0.0
                        if pnl > 0: wins += 1
                        else: losses += 1
                        position = 0 

                    if target_pos != 0 and not warming_up:
                        balance -= (balance * FEE_RATE)
                        entry_price = current_price
                        last_entry_ts = int(time.time()) 
                        position = target_pos
                        
                        state["markers"].append({
                            "time": int(last_row['timestamp'].timestamp()),
                            "position": "belowBar" if position == 1 else "aboveBar",
                            "color": "#22c55e" if position == 1 else "#ef4444",
                            "shape": "circle", "text": f"ENTRADA {'COMPRA' if position==1 else 'VENDA'}"
                        })
                        
                        lado_abertura = "compra (long)" if position == 1 else "venda (short)"
                        state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Abriu {lado_abertura} a US$ {current_price:.2f}"})

                try:
                    if wins + losses > 0:
                        win_rate = (wins / (wins + losses)) * 100
                        current_win_rate = round(min(100.0, max(0.0, win_rate)), 1)
                    else:
                        current_win_rate = state["adaptation"]["current_win_rate"]
                except: current_win_rate = state["adaptation"]["current_win_rate"]
                
                state.update({
                    "in_position": position != 0, "current_position": position, "entry_price": entry_price,
                    "adaptation": {**state["adaptation"], "wins": wins, "losses": losses, "current_win_rate": current_win_rate}
                })

            state["uptime"] = get_uptime()
            if 'last_row' in locals():
                state["last_candle"] = {
                    "time": int(last_row['timestamp'].timestamp()), "open": last_row['open'], 
                    "high": last_row['high'], "low": last_row['low'], "close": last_row['close']
                }
            
            update_safe_state() 
            if loop_counter % 900 == 0: gc.collect() 
            await asyncio.sleep(1.0)
            
        except Exception as e:
            error_str = str(e).lower()
            if "ssl" in error_str or "closed" in error_str or "connectionreset" in error_str:
                try: await exchange.close()
                except: pass
                exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
            await asyncio.sleep(5)

# --- FASTAPI E ROTAS ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(">>> 🚀 FastAPI iniciando lifespan...")
    try:
        async def heartbeat_task():
            while True:
                state["uptime"] = get_uptime()
                update_safe_state() 
                await asyncio.sleep(1.0)
        
        asyncio.create_task(heartbeat_task())
        asyncio.create_task(sniper_loop())
        asyncio.create_task(analyst_market_loop())
        
        if os.path.exists(MODEL_PATH):
            asyncio.create_task(asyncio.to_thread(load_brain, MODEL_PATH))
    except Exception as e:
        print(f">>> ❌ Erro no startup: {e}")
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

@app.get("/ready")
async def readiness_probe():
    if model is None: return {"ready": False, "status": "Modelo carregando...", "code": 503}
    return {"ready": True, "status": "Sistema pronto", "code": 200}

@app.get("/api/state")
async def get_state_snapshot():
    try: return Response(content=global_safe_state_str, media_type="application/json")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e), "status": "offline"}), media_type="application/json", status_code=500)

# 🚀 TICKET 500: HIGIENIZAÇÃO DA ROTA E MANIPULAÇÃO SEGURA
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    try:
        # Accept OBRIGATÓRIO E IMEDIATO antes de qualquer outra lógica!
        await websocket.accept()
        print(f">>> [WS] Conexão ACEITA do cliente: {websocket.client}")
        
        # Registra com segurança
        global connected_clients
        connected_clients.append(websocket)
        
        while True:
            try:
                data_to_send = global_safe_state_str
            except NameError:
                data_to_send = '{"status": "Carregando motor IA..."}'
            
            await websocket.send_text(data_to_send)
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        print(">>> [WS] Cliente desconectado.")
        if websocket in connected_clients: connected_clients.remove(websocket)
    except Exception as e:
        print(f">>> ❌ [WS] Erro Fatal no Loop: {type(e).__name__}: {e}")
        if websocket in connected_clients: connected_clients.remove(websocket)

@app.get("/api/historico")
async def get_historico():
    try:
        if exchange is None:
            temp_ex = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
            ohlcv = await temp_ex.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
            await temp_ex.close()
            return [{"time": int(r[0]/1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
            
        ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
        return [{"time": int(r[0]/1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
    except Exception as e:
        return []

@app.get("/api/download-dados")
async def download_dados(x_admin_password: str = Header(None)):
    if x_admin_password != ADMIN_PASS: raise HTTPException(status_code=401, detail="Acesso Negado.")
    markers = state.get('markers', [])
    if not markers: raise HTTPException(status_code=404, detail="Nenhum dado.")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=markers[0].keys())
    writer.writeheader()
    writer.writerows(markers)
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=live_market_data_{int(time.time())}.csv"})

@app.post("/api/upload-cerebro")
async def upload_cerebro(file: UploadFile = File(...), x_admin_password: str = Header(None)):
    global MODEL_PATH
    if x_admin_password != ADMIN_PASS: raise HTTPException(status_code=401, detail="Acesso Negado.")
    try:
        if not os.path.exists("models"): os.makedirs("models")
        new_model_path = os.path.join("models", file.filename)
        content = await file.read()
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf: zf.testzip()
        except: raise HTTPException(status_code=400, detail=f"Arquivo inválido.")
        with open(new_model_path, "wb") as buffer: buffer.write(content)
        MODEL_PATH = new_model_path
        await asyncio.to_thread(load_brain, MODEL_PATH)
        if model is None: raise Exception("Falha ao carregar.")
        state["adaptation"]["generation"] += 1
        state["adaptation"]["learning_state"] = f"INJETADO ({file.filename})"
        return {"status": "sucesso"}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f">>> 🚀 Iniciando servidor em {host}:{port}")
    
    # 🚀 TICKET 500: LOGS DETALHADOS ATIVADOS (Modo Debug)
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=False,
        # As duas linhas abaixo retiram a mordaça do servidor (Venda removida)
        log_level="debug", 
        access_log=True,
        # Opcional (Aconselhado para Proxy/Render):
        proxy_headers=True, 
        forwarded_allow_ips="*"
    )