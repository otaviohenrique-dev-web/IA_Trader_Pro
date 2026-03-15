from fastapi import FastAPI, WebSocket, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
import shutil
import asyncio
import json
import time
from datetime import datetime
import pandas as pd
import numpy as np
import pandas_ta_classic as ta
import ccxt.async_support as ccxt
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import gc
from sb3_contrib import RecurrentPPO
import warnings

warnings.filterwarnings("ignore")

# --- CONFIGURAÇÕES DO APOCALIPSE (REBOOT) ---
SYMBOL = 'BTC/USDT'
TIMEFRAME = '15m' 
MODEL_PATH = "models/sniper_pro_gen_6.zip" 
DATA_PATH = "data/live_market_data.csv"
START_TIME = time.time()
FEE_RATE = 0.0010 
STOP_LOSS_PCT = -0.010    
TAKE_PROFIT_PCT = +0.020 

# --- VARIÁVEIS DO SIMULADOR E SEGURANÇA ---
balance = 100.00
position = 0 
entry_price = 0.0
wins = 0
losses = 0
DAILY_LOSS_LIMIT = -0.05  
session_start_balance = 100.0  
kill_switch_active = False
max_profit_pct = 0.0  

state = {
    "asset": SYMBOL,
    "is_online": True,
    "in_position": False,
    "entry_price": 0.0,
    "current_position": 0,
    "balance": balance, 
    "status": "REBOOT DO SISTEMA...",
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
        "trades_analyzed": 0,
        "wins": 0,      
        "losses": 0     
    }
}

model = None
exchange = None
lstm_states = None 
episode_starts = np.ones((1,), dtype=bool)
is_training = False 

feature_cols = [
    'log_ret', 'rsi', 'rsi_slope', 'macd_diff', 
    'bb_pband', 'bb_width', 'dist_ema50', 
    'dist_ema200', 'atr_pct'
]

# --- FUNÇÕES DE SUPORTE ---

def run_startup_backtest(df_clean, model_instance):
    print(">>> 🔬 EXECUTANDO BACKTEST DE REBOOT...")
    test_wins, test_losses = 0, 0
    sim_pos, sim_entry = 0, 0.0
    temp_lstm, temp_ep = None, np.ones((1,), dtype=bool)
    
    test_df = df_clean.tail(300)
    for i in range(len(test_df)):
        try:
            obs = test_df[feature_cols].iloc[i].values.astype(np.float32)
            action, temp_lstm = model_instance.predict(obs, state=temp_lstm, episode_start=temp_ep, deterministic=True)
            temp_ep = np.zeros((1,), dtype=bool)
            
            act_idx = action.item() if isinstance(action, np.ndarray) else action
            target_pos = 1 if act_idx == 1 else (-1 if act_idx == 2 else 0)
            
            if target_pos != sim_pos:
                if sim_pos != 0:
                    chg = (test_df.iloc[i]['close'] - sim_entry) / sim_entry
                    pnl = chg if sim_pos == 1 else -chg
                    if pnl > 0: test_wins += 1
                    else: test_losses += 1
                if target_pos != 0: sim_entry = test_df.iloc[i]['close']
                sim_pos = target_pos
        except Exception as e:
            print(f"❌ Erro no Backtest (Step {i}): {e}")
            continue
            
    tot = test_wins + test_losses
    if tot == 0: return 50.0 
    return round((test_wins/tot)*100, 1)

def load_brain(path=MODEL_PATH):
    global model
    print(f">>> 🧠 CARREGANDO CÉREBRO BASE: {path}")
    try:
        if os.path.exists(path):
            model = RecurrentPPO.load(path, device="cpu", tensorboard_log=None) 
            print(">>> CÉREBRO CARREGADO COM SUCESSO!")
        else: 
            print(f">>> ⚠️ AVISO: Modelo {path} não encontrado.")
    except Exception as e: 
        print(f"❌ Erro neural ao carregar: {e}")

def get_uptime():
    seconds = int(time.time() - START_TIME)
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"

# --- LOOP PRINCIPAL (SNIPER) ---

async def sniper_loop():
    global state, exchange, lstm_states, episode_starts, is_training
    global balance, position, entry_price, wins, losses, max_profit_pct
    global kill_switch_active, session_start_balance 
    
    exchange = ccxt.binanceus({'enableRateLimit': True})
    print(f">>> 🚀 CONECTADO AO MERCADO REAL. AGUARDANDO ALVOS...")

    startup_phase = True
    startup_timer = 0
    warming_up = True 
    warmup_counter = 0
    consecutive_signals = 0 
    last_signal = 0   
    last_saved_candle_ts = 0 

    while True:
        try:
            ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            closed_candle_ts = ohlcv[-2][0] 
            
            if closed_candle_ts > last_saved_candle_ts:
                if not os.path.exists("data"): os.makedirs("data")
                if os.path.exists(DATA_PATH):
                    df.iloc[:-1].tail(1).to_csv(DATA_PATH, mode='a', header=False, index=False)
                else:
                    df.iloc[:-1].to_csv(DATA_PATH, index=False)
                last_saved_candle_ts = closed_candle_ts
                print(f">>> 💾 Mercado Logado no CSV. Vela: {pd.to_datetime(closed_candle_ts, unit='ms')}")

            # --- PROCESSAMENTO DE INDICADORES ---
            df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['rsi_slope'] = df['rsi'].diff()
            
            # 🛡️ Inicialização das Bandas de Bollinger para evitar erro de Index
            df['bb_pband'] = 0.0
            df['bb_width'] = 0.0

            macd = ta.macd(df['close'])
            if macd is not None:
                macd_col = [c for c in macd.columns if c.startswith('MACDh') or c.startswith('MACDH')][0]
                df['macd_diff'] = macd[macd_col]
            else:
                df['macd_diff'] = 0.0

            bb = ta.bbands(df['close'], length=20, std=2)
            if bb is not None:
                try:
                    u_col = [c for c in bb.columns if c.startswith('BBU')][0]
                    l_col = [c for c in bb.columns if c.startswith('BBL')][0]
                    w_col = [c for c in bb.columns if c.startswith('BBB')][0]
                    df['bb_pband'] = (df['close'] - bb[l_col]) / (bb[u_col] - bb[l_col])
                    df['bb_width'] = bb[w_col]
                except Exception: pass

            df['sma200'] = ta.sma(df['close'], length=200)
            df['ema50'] = ta.ema(df['close'], length=50)
            df['ema200'] = ta.ema(df['close'], length=200)
            df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
            df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            df['atr_pct'] = df['atr'] / df['close']

            df_clean = df.dropna().copy()

            if model and len(df_clean) > 0:
                if startup_phase:
                    state["status"] = "REBOOT: EXECUTANDO BACKTEST..."
                    startup_timer += 1
                    if startup_timer == 1:
                        real_baseline = run_startup_backtest(df_clean, model)
                        state["adaptation"]["initial_win_rate"] = real_baseline
                        state["adaptation"]["current_win_rate"] = real_baseline
                    if startup_timer > 2: startup_phase = False
                else:
                    last_row = df_clean.iloc[-1]
                    obs = last_row[feature_cols].values.astype(np.float32)
                    
                    macro_trend = 1 if last_row['close'] > last_row['sma200'] else -1
                    current_session_pnl = (balance - session_start_balance) / session_start_balance
                    if current_session_pnl <= DAILY_LOSS_LIMIT:
                        kill_switch_active = True

                    action, lstm_states = model.predict(obs, state=lstm_states, episode_start=episode_starts, deterministic=True)
                    episode_starts = np.zeros((1,), dtype=bool)
                    act_idx = action.item()
                    
                    current_price = float(last_row['close'])
                    current_ts = int(ohlcv[-1][0] / 1000) 
                    target_pos = position 
                    is_choppy = float(last_row['atr_pct']) < 0.0015 

                    if warming_up:
                        warmup_counter += 1
                        state["status"] = f"🛡️ AQUECIMENTO... ({warmup_counter}/10)"
                        if warmup_counter >= 10: warming_up = False
                    else:
                        if act_idx != 0 and act_idx == last_signal: consecutive_signals += 1
                        elif act_idx != 0: consecutive_signals = 1; last_signal = act_idx
                        else: consecutive_signals = 0; last_signal = 0

                        if kill_switch_active:
                            target_pos = 0
                            state["status"] = "🛑 KILL-SWITCH ATIVADO."
                        elif act_idx == 0:
                            target_pos = 0
                        elif is_choppy and position == 0:
                            target_pos = 0 
                            state["status"] = "💤 MERCADO LATERAL"
                        elif consecutive_signals >= 2:
                            if act_idx == 1: target_pos = 1 if macro_trend == 1 else 0
                            elif act_idx == 2: target_pos = -1 if macro_trend == -1 else 0
                            consecutive_signals = 0 
                        else:
                            state["status"] = f"🔍 ANALISANDO {'LONG' if act_idx == 1 else 'SHORT'}..."

                    # --- GESTÃO DE RISCO ---
                    if not warming_up and position != 0:
                        change_pct = (current_price - entry_price) / entry_price
                        unrealized_pct = change_pct if position == 1 else -change_pct
                        if unrealized_pct > max_profit_pct: max_profit_pct = unrealized_pct
                        
                        dynamic_stop = STOP_LOSS_PCT 
                        if max_profit_pct >= 0.015: dynamic_stop = max_profit_pct - 0.006
                        elif max_profit_pct >= 0.008: dynamic_stop = 0.002

                        if unrealized_pct <= dynamic_stop:
                            target_pos = 0  
                            state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ STOP ({unrealized_pct*100:.2f}%)"})

                    # --- EXECUÇÃO ---
                    if target_pos != position:
                        if position != 0: 
                            pnl = (balance * ((current_price - entry_price) / entry_price)) if position == 1 else (balance * -((current_price - entry_price) / entry_price))
                            balance += (pnl - (balance * FEE_RATE))
                            state["balance"] = balance
                            cor = "🟢" if pnl >= 0 else "🔴"
                            state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] {cor} FECHOU | PnL: ${pnl:.2f}"})
                            if pnl > 0: wins += 1
                            else: losses += 1
                            state["adaptation"]["wins"], state["adaptation"]["losses"] = wins, losses
                            if (wins + losses) > 0: state["adaptation"]["current_win_rate"] = round((wins / (wins + losses)) * 100, 1)

                        if target_pos != 0:
                            balance -= (balance * FEE_RATE)
                            entry_price, max_profit_pct = current_price, 0.0
                            label = "LONG 🟢" if target_pos == 1 else "SHORT 🔴"
                            state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 ABRIU {label} em ${current_price:.2f}"})
                        position = target_pos
                        state["in_position"] = (position != 0)
                        state["current_position"], state["entry_price"] = position, entry_price

            # ATUALIZAÇÃO DO GRÁFICO
            last_100 = df_clean.tail(100)
            state["chart_data"] = [{"time": int(r['timestamp'].timestamp()), "open": r['open'], "high": r['high'], "low": r['low'], "close": r['close'], "rsi": r['rsi'], "bb_width": r['bb_width']} for _, r in last_100.iterrows()]
            state["last_candle"] = state["chart_data"][-1]
            state["uptime"] = get_uptime()
            
            gc.collect() 
            await asyncio.sleep(10)

        except Exception as e:
            print(f"❌ Erro no Loop: {e}")
            await asyncio.sleep(5)

# --- ENDPOINTS API ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    state["adaptation"]["generation"] = 1
    load_brain(MODEL_PATH)
    loop_task = asyncio.create_task(sniper_loop())
    yield
    loop_task.cancel()
    if exchange: await exchange.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
@app.head("/")
async def health_check():
    return {"status": "IA Trader Pro REBOOT Online!"}

@app.get("/api/historico")
async def get_historico():
    try:
        ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
        return [{"time": int(r[0]/1000), "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in ohlcv]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download-dados")
async def download_dados(senha: str):
    admin_pass = os.environ.get("ADMIN_PASSWORD", "senha_padrao_secreta")
    if senha != admin_pass: raise HTTPException(status_code=403, detail="Senha Incorreta.")
    return FileResponse(DATA_PATH, media_type='text/csv', filename=f"reboot_data_{datetime.now().strftime('%Y%m%d')}.csv")

@app.post("/upload-cerebro")
async def upload_cerebro(senha: str, file: UploadFile = File(...)):
    admin_pass = os.environ.get("ADMIN_PASSWORD", "senha_padrao_secreta")
    if senha != admin_pass: raise HTTPException(status_code=403, detail="Acesso Negado.")
    global balance, session_start_balance, kill_switch_active, wins, losses, lstm_states, episode_starts
    new_gen = state["adaptation"]["generation"] + 1
    new_path = f"models/sniper_pro_gen_{new_gen}.zip"
    with open(new_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    load_brain(new_path)
    lstm_states, episode_starts = None, np.ones((1,), dtype=bool)
    wins, losses, session_start_balance, kill_switch_active = 0, 0, balance, False 
    state["adaptation"].update({"wins": 0, "losses": 0, "current_win_rate": 0.0, "generation": new_gen, "learning_state": "ATIVO"})
    return {"mensagem": f"Geração {new_gen} ativa!"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(state)
            await asyncio.sleep(1)
    except Exception: pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))