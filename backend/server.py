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
from starlette.websockets import WebSocketState
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
DATA_PATH = "data/live_market_data.csv"
START_TIME = time.time()
FEE_RATE = 0.0010 
STOP_LOSS_PCT = -0.010    
TAKE_PROFIT_PCT = +0.020 

load_dotenv()

CRYPTOCOMPARE_KEY = os.environ.get("CRYPTOCOMPARE_API_KEY") or os.environ.get("CRYPTOCOMPARE_KEY") or ""
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")

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

startup_phase = True
startup_timer = 0
warming_up = True 
warmup_counter = 0
consecutive_signals = 0 
last_signal = 0   
last_entry_ts = 0

state = {
    "asset": SYMBOL,
    "is_online": True,
    "in_position": False,
    "entry_price": 0.0,
    "current_position": 0,
    "balance": balance, 
    "status": "Iniciando Sniper...",
    "uptime": "00:00:00",
    "last_candle": {},
    "chart_data": [],
    "markers": [],
    "order_book": [], 
    "adaptation": {
        "generation": 1,
        "learning_state": "SISTEMA ONLINE",
        "initial_win_rate": 0.0,
        "current_win_rate": 0.0,
        "wins": 0,      
        "losses": 0     
    },
    "news_agent": {
        "status": "SAFE",
        "sentiment_score": 0.0,
        "risk_level": "BAIXO",
        "last_headlines": []
    }
}

model = None
exchange = None
lstm_states = None 
episode_starts = np.ones((1,), dtype=bool)
feature_cols = ['log_ret', 'rsi', 'rsi_slope', 'macd_diff', 'bb_pband', 'bb_width', 'dist_ema50', 'dist_ema200', 'atr_pct']
last_analysis_time = 0
cached_analysis = {"score": 50, "status": "SAFE", "reason": "Sincronizando..."}

# Inicialização de segurança para o WebSocket
global_safe_state_str = '{"status": "Aguardando sincronização neural..."}'
connected_clients = []

def update_safe_state():
    """Sanitiza e empacota o estado APENAS quando ele sofre alterações."""
    global global_safe_state_str
    try:
        # Cria uma cópia profunda para evitar mutação durante a sanitização
        safe_state = clean_nans(copy.deepcopy(state))
        
        # Otimizações de memória aplicadas na raiz
        if safe_state.get("markers") and len(safe_state["markers"]) > 50:
            safe_state["markers"] = safe_state["markers"][-50:]
        if safe_state.get("order_book") and len(safe_state["order_book"]) > 30:
            safe_state["order_book"] = safe_state["order_book"][:30]
        
        global_safe_state_str = json.dumps(safe_state)
    except Exception as e:
        print(f">>> ❌ Erro ao sanitizar estado: {e}")

def run_startup_backtest(df_clean, model_instance):
    if model_instance is None: return 50.0
    test_wins, test_losses = 0, 0
    sim_pos, sim_entry = 0, 0.0
    temp_lstm, temp_ep = None, np.ones((1,), dtype=bool)
    test_df = df_clean.tail(100)
    for i in range(len(test_df)):
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
    return round((test_wins/tot)*100, 1) if tot > 0 else 50.0

def load_brain(path=MODEL_PATH):
    global model
    try:
        if os.path.exists(path):
            import zipfile
            if zipfile.is_zipfile(path):
                gc.collect()
                model = RecurrentPPO.load(path, device="cpu")
                print(f">>> 🧠 [Cérebro] Modelo '{path}' carregado com sucesso.")
    except: model = None
    finally: gc.collect()

def get_uptime():
    seconds = int(time.time() - START_TIME)
    return time.strftime('%H:%M:%S', time.gmtime(seconds))

from google import genai
try:
    client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
except: client = None

_NEWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

async def _cryptocompare_news_titles(session, query: str, headers: dict) -> list:
    key_q = f"&api_key={CRYPTOCOMPARE_KEY}" if CRYPTOCOMPARE_KEY else ""
    url = f"https://min-api.cryptocompare.com/data/v2/news/?{query}{key_q}"
    try:
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get("Data", [])
                return [f" {p['title']} •" for p in results[:10]] if results else []
            return ["API_ESGOTADA"] if resp.status == 429 else []
    except: return []

async def fetch_btc_news():
    headers = {"User-Agent": _NEWS_UA}
    try:
        async with aiohttp.ClientSession() as session:
            titles = await _cryptocompare_news_titles(session, "categories=BTC&lang=PT", headers)
            if not titles or titles[0] == "API_ESGOTADA":
                titles = await _cryptocompare_news_titles(session, "categories=BTC&lang=EN", headers)
            return titles
    except: return []

async def analyze_sentiment_with_llm(headlines):
    """Usa o modelo Gemini 3 Flash Preview calibrado para ignorar ruído."""
    
    global last_analysis_time, cached_analysis
    current_time = time.time()
    
    # 🚀 AÇÃO 1 CONCLUÍDA: TRAVA DO CACHE de 3600 segundos (1 hora)
    if current_time - last_analysis_time < 3600:
        print(">>> ⏳ IA em Cooldown. Retornando análise de risco do cache para economizar cota.")
        return cached_analysis

    if not headlines:
        return {"score": 0.1, "status": "SAFE", "reason": "Mercado calmo (Sem notícias)"}
    
    if not client:
        print(">>> ⚠️ Cliente Genai não disponível. Retornando análise segura (SAFE).")
        return {"score": 0.1, "status": "SAFE", "reason": "Cliente IA indisponível - modo técnico"}
    
    prompt = f"""
    Você é um Gestor de Risco Quantitativo sênior de Bitcoin. Avalie o risco macroeconômico atual baseado nestas manchetes (em português ou inglês):
    {headlines}

    REGULAGEM DE RISCO ESTREITA (O mercado cripto é naturalmente volátil, ignore o sensacionalismo):
    - Score 0.0 a 0.60 (SAFE): Notícias de adoção, ETFs, desenvolvimentos técnicos, ou FUD genérico (ex: "analista prevê queda", oscilações normais, correções pequenas). O bot PODE operar.
    - Score 0.61 a 0.80 (CAUTION): Notícias macroeconômicas ruins REAIS (ex: aumento severo de juros do FED, inflação muito acima do esperado, hack de corretora média).
    - Score 0.81 a 1.0 (DANGER): Eventos catastróficos globais, falência de top 3 corretoras (estilo FTX), banimento em grandes potências, guerras em grande escala.

    Responda APENAS em JSON puro: {{"score": float, "status": "SAFE" ou "CAUTION" ou "DANGER", "reason": "resumo de 1 linha do sentimento geral"}}
    """
    
    try:
        response = await asyncio.to_thread(
            client.models.generate_content, 
            model="gemini-3-flash-preview", 
            contents=prompt
        )
        
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_text)
        
        score = float(data.get("score", 0.0))
        if score > 1.0: score = score / 10.0 if score <= 10.0 else 1.0
        
        # 🚀 AÇÃO 2 CONCLUÍDA: Expansão da Tolerância de Risco (Filtro FUD até 0.60)
        data["status"] = "SAFE" if score <= 0.60 else ("CAUTION" if score <= 0.80 else "DANGER")
            
        data["score"] = score
        
        cached_analysis = data
        last_analysis_time = current_time
        
        return data
        
    except Exception as e:
        print(f"⚠️ Erro na análise da IA: {e}")
        return cached_analysis

async def analyst_market_loop():
    print(">>> 🕵️ IA_ANALISTA: Iniciando Sentinela de Mercado...")
    
    global kill_switch_active
    headers = {"User-Agent": _NEWS_UA}
    print(">>> ✅ IA_ANALISTA: Pronto para análise de notícias")
    
    while True:
        try:
            headlines = await fetch_btc_news()

            # Fallback: feed geral CryptoCompare (PT, depois EN se vazio)
            if not headlines:
                async with aiohttp.ClientSession() as session:
                    for q in ("lang=PT", "lang=EN"):
                        headlines = await _cryptocompare_news_titles(session, q, headers)
                        if headlines:
                            break

            # --- CIRCUITO DE PROTEÇÃO CONTRA COTA ESGOTADA ---
            if headlines and headlines[0] == "API_ESGOTADA":
                print(">>> ⚠️ API de Notícias Esgotada. Entrando em MODO 100% TÉCNICO.")
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
            
            if analysis["status"] == "SAFE":
                kill_switch_active = False
            
            update_safe_state() 
            
            print(f">>> ✅ Analista: {analysis['status']} | Letreiro atualizado com {len(headlines)} notícias.")
            
            # 🚀 AÇÃO 1 CONCLUÍDA: Descanso de 1 hora (Consumo Inteligente)
            await asyncio.sleep(3600) 
            
        except Exception as e:
            print(f"❌ Erro no Analista: {e}")
            await asyncio.sleep(60)

async def sniper_loop():
    global state, exchange, lstm_states, episode_starts, balance, position, entry_price, wins, losses, kill_switch_active, last_entry_ts, startup_phase, startup_timer, warming_up, warmup_counter, consecutive_signals, last_signal
    try:
        exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
    except: return
    
    model_wait_start = time.time()
    while model is None and (time.time() - model_wait_start) < 15: await asyncio.sleep(1)
    
    loop_counter = 0 
    last_fetch_ts = 0
    while True:
        loop_counter += 1
        try:
            now_ts = time.time()
            if now_ts - last_fetch_ts > 60:
                ohlcv = await asyncio.wait_for(exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=250), timeout=15.0)
                def process_indicators(ohlcv_data):
                    df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
                    df['rsi'] = ta.rsi(df['close'], length=14)
                    df['rsi_slope'] = df['rsi'].diff()
                    macd = ta.macd(df['close'])
                    df['macd_diff'] = macd[[c for c in macd.columns if 'MACDh' in c][0]] if macd is not None else 0.0
                    bb = ta.bbands(df['close'], length=20, std=2)
                    if bb is not None:
                        df['bb_pband'] = (df['close'] - bb[[c for c in bb.columns if 'BBL' in c][0]]) / (bb[[c for c in bb.columns if 'BBU' in c][0]] - bb[[c for c in bb.columns if 'BBL' in c][0]])
                        df['bb_width'] = bb[[c for c in bb.columns if 'BBB' in c][0]]
                    df['ema50'], df['ema200'] = ta.ema(df['close'], length=50), ta.ema(df['close'], length=200)
                    df['dist_ema50'], df['dist_ema200'] = (df['close']-df['ema50'])/df['ema50'], (df['close']-df['ema200'])/df['ema200']
                    df['atr_pct'] = ta.atr(df['high'], df['low'], df['close'], length=14) / df['close']
                    return df, df.dropna().copy()
                
                df, df_clean = await asyncio.to_thread(process_indicators, ohlcv)
                last_fetch_ts = now_ts

            if 'df_clean' in locals() and len(df_clean) > 0:
                last_row = df_clean.iloc[-1]
                current_price = float(last_row['close'])
                target_pos = position 
                state["display_balance"] = balance + (balance * ((current_price - entry_price)/entry_price if position == 1 else (entry_price - current_price)/entry_price) if position != 0 else 0)

                if startup_phase:
                    if model is None: await asyncio.sleep(0.5); continue
                    startup_timer += 1
                    if startup_timer == 1:
                        res = await asyncio.to_thread(run_startup_backtest, df_clean, model)
                        state["adaptation"]["initial_win_rate"] = res
                        print(f">>> 🚀 [Sistema] Sniper pronto. Backtest inicial: {res}%")
                    if startup_timer > 2: startup_phase = False
                elif warming_up:
                    warmup_counter += 1
                    if warmup_counter >= 15: warming_up = False; state["status"] = "📊 AGUARDANDO SINAL..."
                else:
                    if model is not None:
                        obs = last_row[feature_cols].values.astype(np.float32)
                        action, lstm_states = await asyncio.to_thread(model.predict, obs, state=lstm_states, episode_start=episode_starts, deterministic=True)
                        episode_starts = np.zeros((1,), dtype=bool)
                        act_idx = action.item()
                        if act_idx != 0 and act_idx == last_signal: consecutive_signals += 1
                        elif act_idx != 0: consecutive_signals = 1; last_signal = act_idx
                        else: consecutive_signals = 0; last_signal = 0

                        if position != 0:
                            rem = 900 - (int(time.time()) - last_entry_ts)
                            if rem > 0: target_pos = position; state["status"] = f"PROTEÇÃO: {rem}s"
                            else: state["status"] = "📊 MONITORANDO..."; target_pos = 0 if act_idx == 0 else position
                        # O bot opera livremente a menos que o Kill Switch (DANGER) esteja ativado
                        elif position == 0 and not kill_switch_active and consecutive_signals >= 3:
                            target_pos = 1 if act_idx == 1 else (-1 if act_idx == 2 else 0)

                if target_pos != position:
                    if position != 0:
                        pnl = (balance * ((current_price - entry_price)/entry_price)) if position == 1 else (balance * -((current_price - entry_price)/entry_price))
                        balance += (pnl - (balance * FEE_RATE))
                        state["markers"].append({"time": int(last_row['timestamp'].timestamp()), "position": "aboveBar", "color": "#facc15", "shape": "square", "text": f"SAÍDA: {'GANHO' if pnl > 0 else 'PERDA'}"})
                        state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🏁 Posição Fechada | PnL: US$ {pnl:.2f}"})
                        print(f">>> 🏁 [Trade] Fechou {'LONG' if position==1 else 'SHORT'} | PnL: ${pnl:.2f}")
                        if pnl > 0: wins += 1
                        else: losses += 1
                        position = 0
                    if target_pos != 0 and not warming_up:
                        balance -= (balance * FEE_RATE)
                        entry_price, last_entry_ts, position = current_price, int(time.time()), target_pos
                        state["markers"].append({"time": int(last_row['timestamp'].timestamp()), "position": "belowBar" if position == 1 else "aboveBar", "color": "#22c55e" if position == 1 else "#ef4444", "shape": "circle", "text": f"ENTRADA {'COMPRA' if position==1 else 'VENDA'}"})
                        state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Nova Posição a US$ {current_price:.2f}"})
                        print(f">>> 🚀 [Trade] Abriu {'LONG' if position==1 else 'SHORT'} a ${current_price:.2f}")

                state.update({"in_position": position != 0, "current_position": position, "entry_price": entry_price, "balance": balance, "adaptation": {**state["adaptation"], "wins": wins, "losses": losses, "current_win_rate": round((wins/(wins+losses)*100),1) if wins+losses>0 else 0}})
            
            state["uptime"] = get_uptime()
            if 'last_row' in locals(): state["last_candle"] = {"time": int(last_row['timestamp'].timestamp()), "open": last_row['open'], "high": last_row['high'], "low": last_row['low'], "close": last_row['close']}
            update_safe_state()
            if loop_counter % 900 == 0: gc.collect() 
            await asyncio.sleep(1.0)
        except Exception as e:
            if "ssl" in str(e).lower(): exchange = ccxt.kraken({'enableRateLimit': True, 'timeout': 30000})
            await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(">>> 🚀 [Sistema] IA Trader Pro v3.0.1 Online.")
    asyncio.create_task(sniper_loop())
    asyncio.create_task(analyst_market_loop())
    asyncio.create_task(asyncio.to_thread(load_brain))
    yield

app = FastAPI(lifespan=lifespan)
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/state")
async def get_state_snapshot():
    return Response(content=global_safe_state_str, media_type="application/json")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Gerencia a lista global de clientes sem condicionais perigosas
    global connected_clients
    connected_clients.append(websocket)
    
    try:
        while True:
            # Envia a string global que já está sendo atualizada no loop principal
            await websocket.send_text(global_safe_state_str)
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
    except Exception as e:
        print(f">>> ❌ Erro Crítico no WS: {e}")

@app.get("/api/historico")
async def get_historico():
    try:
        ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
        return [{"time": int(r[0]/1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
    except: return []

@app.get("/api/download-dados")
async def download_dados(x_admin_password: str = Header(None)):
    if x_admin_password != ADMIN_PASS: raise HTTPException(status_code=401)
    import io, csv
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=state['markers'][0].keys() if state['markers'] else [])
    writer.writeheader(); writer.writerows(state['markers'])
    output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=history.csv"})

@app.post("/api/upload-cerebro")
async def upload_cerebro(file: UploadFile = File(...), x_admin_password: str = Header(None)):
    if x_admin_password != ADMIN_PASS: raise HTTPException(status_code=401)
    try:
        path = os.path.join("models", file.filename)
        with open(path, "wb") as buffer: buffer.write(await file.read())
        await asyncio.to_thread(load_brain, path)
        state["adaptation"]["generation"] += 1
        return {"status": "sucesso"}
    except: raise HTTPException(status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=10000, log_level="warning", access_log=False)