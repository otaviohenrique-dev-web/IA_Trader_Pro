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

# --- CONFIGURAÇÕES DO APOCALIPSE ---
SYMBOL = 'BTC/USDT'
TIMEFRAME = '15m' # 🛡️ SOLUÇÃO 3: Filtro de Ruído Natural (15 minutos)
MODEL_PATH = "models/sniper_pro_gen_6.zip" 
DATA_PATH = "data/live_market_data.csv"
START_TIME = time.time()

FEE_RATE = 0.0010 

STOP_LOSS_PCT = -0.010   
TAKE_PROFIT_PCT = +0.020 

# --- VARIÁVEIS DO SIMULADOR ---
balance = 100.00
position = 0 
entry_price = 0.0
wins = 0
losses = 0
max_profit_pct = 0.0  

state = {
    "asset": SYMBOL,
    "is_online": True,
    "in_position": False,
    "entry_price": 0.0,
    "current_position": 0,
    "balance": balance, 
    "status": "INICIANDO MOTORES...",
    "uptime": "00:00:00",
    "last_candle": {},
    "chart_data": [],
    "markers": [],
    "order_book": [], 
    "adaptation": {
        "generation": 4,
        "learning_state": "OBSERVANDO",
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

def run_startup_backtest(df_clean, model_instance):
    print(">>> 🔬 EXECUTANDO BACKTEST DE AQUECIMENTO...")
    test_wins, test_losses = 0, 0
    sim_pos, sim_entry = 0, 0.0
    temp_lstm, temp_ep = None, np.ones((1,), dtype=bool)
    
    test_df = df_clean.tail(300)
    for i in range(len(test_df)):
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
            
    tot = test_wins + test_losses
    if tot == 0: return 50.0 
    return round((test_wins/tot)*100, 1)

def get_latest_model():
    if not os.path.exists("models"): os.makedirs("models")
    files = [f for f in os.listdir("models") if f.startswith("sniper_pro_gen_") and f.endswith(".zip")]
    if not files: return MODEL_PATH, 1
    try:
        gens = [int(f.split("_")[3].split(".")[0]) for f in files]
        return f"models/sniper_pro_gen_{max(gens)}.zip", max(gens)
    except: return MODEL_PATH, 1

def load_brain(path=MODEL_PATH):
    global model
    print(f">>> 🧠 DESPERTANDO O CÉREBRO: {path}")
    try:
        if os.path.exists(path):
            model = RecurrentPPO.load(path, device="cpu", tensorboard_log=None) 
            print(">>> CÉREBRO CARREGADO COM SUCESSO!")
        else: print(f">>> ⚠️ AVISO: Modelo {path} não encontrado.")
    except Exception as e: print(f"❌ Erro neural ao carregar: {e}")

def run_training_thread(current_gen):
    from envs.trading_env import BitcoinTradingEnv
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧬 EVOLUINDO PARA GEN {current_gen + 1}...")
    try:
        if not os.path.exists(DATA_PATH): return None
        df = pd.read_csv(DATA_PATH)
        df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['rsi_slope'] = df['rsi'].diff()
        macd = ta.macd(df['close'])
        if macd is not None:
            macd_col = [c for c in macd.columns if c.startswith('MACDh') or c.startswith('MACDH')][0]
            df['macd_diff'] = macd[macd_col]
        bb = ta.bbands(df['close'], length=20, std=2)
        if bb is not None:
            upper_col = [c for c in bb.columns if c.startswith('BBU')][0]
            lower_col = [c for c in bb.columns if c.startswith('BBL')][0]
            width_col = [c for c in bb.columns if c.startswith('BBB')][0]
            df['bb_pband'] = (df['close'] - bb[lower_col]) / (bb[upper_col] - bb[lower_col])
            df['bb_width'] = bb[width_col]
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema200'] = ta.ema(df['close'], length=200)
        df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
        df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['atr_pct'] = df['atr'] / df['close']
        
        env = BitcoinTradingEnv(df.dropna().copy())
        global model
        model = RecurrentPPO.load(MODEL_PATH, env=env, device="cpu", tensorboard_log=None)
        model.learn(total_timesteps=5000)
        new_path = f"models/sniper_pro_gen_{current_gen + 1}.zip"
        model.save(new_path)
        return new_path
    except Exception as e:
        print(f"❌ Erro crítico no treino: {e}")
        return None

async def evolve_apocalypse():
    global is_training, state, model, lstm_states, episode_starts
    is_training = True
    state["adaptation"]["learning_state"] = "TREINANDO NOVA GERAÇÃO"
    state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] 🧬 PROTOCOLO APOCALIPSE: Evolução Iniciada."})
    
    try:
        current_gen = state["adaptation"]["generation"]
        new_model_path = await asyncio.to_thread(run_training_thread, current_gen)
        if new_model_path:
            load_brain(new_model_path)
            lstm_states = None 
            episode_starts = np.ones((1,), dtype=bool)
            state["adaptation"]["generation"] += 1
            state["adaptation"]["learning_state"] = "EVOLUÇÃO CONCLUÍDA. NOVO CÉREBRO ATIVO."
    except Exception as e:
        state["adaptation"]["learning_state"] = "FALHA NA EVOLUÇÃO."
    is_training = False

def get_uptime():
    seconds = int(time.time() - START_TIME)
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"

async def sniper_loop():
    global state, exchange, lstm_states, episode_starts, is_training
    global balance, position, entry_price, wins, losses, max_profit_pct
    
    exchange = ccxt.binanceus({'enableRateLimit': True})
    print(f">>> 🚀 CONECTADO AO MERCADO REAL (BINANCE US). AGUARDANDO ALVOS...")

    startup_phase = True
    startup_timer = 0
    warming_up = True 
    warmup_counter = 0
    consecutive_signals = 0 
    last_signal = 0   
    last_trade_ts = 0      
    cooldown_until_ts = 0  
    
    last_saved_candle_ts = 0 

    while True:
        try:
            ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            current_candle_ts = ohlcv[-1][0]
            closed_candle_ts = ohlcv[-2][0] 
            
            if closed_candle_ts > last_saved_candle_ts:
                if os.path.exists(DATA_PATH):
                    df_hist = pd.read_csv(DATA_PATH)
                    df_hist = pd.concat([df_hist, df.iloc[:-1]]).drop_duplicates(subset=['timestamp']).tail(2000)
                    df_hist.to_csv(DATA_PATH, index=False)
                else:
                    if not os.path.exists("data"): os.makedirs("data")
                    df.iloc[:-1].to_csv(DATA_PATH, index=False)
                
                last_saved_candle_ts = closed_candle_ts
                print(f">>> 💾 Mercado Logado no CSV. Vela Fechada: {pd.to_datetime(closed_candle_ts, unit='ms')}")

            df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['rsi_slope'] = df['rsi'].diff()
            macd = ta.macd(df['close'])
            df['macd_diff'] = macd[[c for c in macd.columns if c.startswith('MACDh') or c.startswith('MACDH')][0]] if macd is not None else 0
            bb = ta.bbands(df['close'], length=20, std=2)
            if bb is not None:
                upper, lower, width = [c for c in bb.columns if c.startswith('BBU')][0], [c for c in bb.columns if c.startswith('BBL')][0], [c for c in bb.columns if c.startswith('BBB')][0]
                df['bb_pband'] = (df['close'] - bb[lower]) / (bb[upper] - bb[lower])
                df['bb_width'] = bb[width]
            else:
                df['bb_pband'] = 0; df['bb_width'] = 0
            
            df['ema50'] = ta.ema(df['close'], length=50)
            df['ema200'] = ta.ema(df['close'], length=200)
            df['dist_ema50'] = (df['close'] - df['ema50']) / df['ema50']
            df['dist_ema200'] = (df['close'] - df['ema200']) / df['ema200']
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            df['atr_pct'] = df['atr'] / df['close']

            df_clean = df.dropna().copy()

            if model and len(df_clean) > 0:
                if startup_phase:
                    state["status"] = "ESTABILIZANDO INDICADORES & EXECUTANDO BACKTEST..."
                    startup_timer += 1
                    if startup_timer == 1:
                        real_baseline = run_startup_backtest(df_clean, model)
                        state["adaptation"]["initial_win_rate"] = real_baseline
                        state["adaptation"]["current_win_rate"] = real_baseline
                        print(f">>> 🎯 BACKTEST CONCLUÍDO! Baseline Real: {real_baseline}%")
                    if startup_timer > 3: startup_phase = False
                else:
                    last_row = df_clean.iloc[-1]
                    obs = last_row[feature_cols].values.astype(np.float32)
                    action, lstm_states = model.predict(obs, state=lstm_states, episode_start=episode_starts, deterministic=True)
                    episode_starts = np.zeros((1,), dtype=bool)
                    act_idx = action.item()
                    
                    horario = datetime.now().strftime("%H:%M:%S")
                    current_price = float(last_row['close'])
                    current_ts = int(ohlcv[-1][0] / 1000) 
                    target_pos = position 

                    # 🛡️ SOLUÇÃO 1: O Escudo de Volatilidade (Evita o Chop Market da Madrugada)
                    current_atr_pct = float(last_row['atr_pct'])
                    is_choppy = current_atr_pct < 0.0015 # Volatilidade menor que 0.15%

                    if warming_up:
                        warmup_counter += 1
                        state["status"] = f"🛡️ AQUECIMENTO TÉCNICO... ({warmup_counter}/10)"
                        if warmup_counter >= 10: warming_up = False
                    else:
                        if act_idx != 0 and act_idx == last_signal: consecutive_signals += 1
                        elif act_idx != 0: consecutive_signals = 1; last_signal = act_idx
                        else: consecutive_signals = 0; last_signal = 0

                        # Aplicação do Escudo
                        if act_idx == 0: 
                            target_pos = 0
                        elif is_choppy and position == 0:
                            target_pos = 0 # Força a ficar de fora da operação
                            state["status"] = f"💤 MERCADO LATERAL. CÉREBRO EM ESPERA (ATR: {current_atr_pct*100:.2f}%)"
                            consecutive_signals = 0
                        elif consecutive_signals >= 2: 
                            target_pos = 1 if act_idx == 1 else -1
                            consecutive_signals = 0 
                        else:
                            state["status"] = f"🔍 VALIDANDO {'LONG' if act_idx == 1 else 'SHORT'}... ({consecutive_signals}/2)"

                        if target_pos != 0 and position == 0 and current_ts < cooldown_until_ts:
                            target_pos = 0
                            min_restantes = int((cooldown_until_ts - current_ts) / 60)
                            state["status"] = f"🧊 COOLDOWN: Analisando erro passado. Retorno em {min_restantes} min..."

                    # 🛡️ GESTÃO DE RISCO DINÂMICA
                    if not warming_up and position != 0:
                        change_pct = (current_price - entry_price) / entry_price
                        unrealized_pct = change_pct if position == 1 else -change_pct
                        
                        if unrealized_pct > max_profit_pct:
                            max_profit_pct = unrealized_pct

                        dynamic_stop = STOP_LOSS_PCT 
                        stop_type = "STOP LOSS"

                        if max_profit_pct >= 0.015: 
                            dynamic_stop = max_profit_pct - 0.006
                            stop_type = "TRAILING STOP"
                        elif max_profit_pct >= 0.008:
                            dynamic_stop = 0.002
                            stop_type = "BREAKEVEN"

                        if unrealized_pct <= dynamic_stop:
                            target_pos = 0  
                            horario_log = datetime.now().strftime("%H:%M:%S")
                            cor_log = "🎯" if dynamic_stop > 0 else "🛡️"
                            state["order_book"].insert(0, {"text": f"[{horario_log}] {cor_log} {stop_type} ACIONADO ({unrealized_pct*100:.2f}%)"})

                    if target_pos != 0 and position == 0 and current_ts == last_trade_ts:
                        target_pos = 0 
                        state["status"] = "⏳ AGUARDANDO NOVA VELA PARA OPERAR..."

                    if target_pos != position:
                        # FECHAMENTO DA OPERAÇÃO
                        if position != 0:
                            change_pct = (current_price - entry_price) / entry_price
                            pnl = (balance * change_pct) if position == 1 else (balance * -change_pct)
                            fee = balance * FEE_RATE
                            balance += (pnl - fee)
                            state["balance"] = balance
                            
                            cor = "🟢" if pnl >= 0 else "🔴"
                            state["order_book"].insert(0, {"text": f"[{horario}] {cor} FECHOU POSIÇÃO | PnL: ${pnl:.2f}"})
                            
                            fechamento_cor = "#22c55e" if pnl > 0 else "#ef4444"
                            fechamento_texto = "WIN" if pnl > 0 else "LOSS"
                            fechamento_pos = "belowBar" if pnl > 0 else "aboveBar"
                            
                            state["markers"].append({"time": current_ts, "position": fechamento_pos, "color": fechamento_cor, "shape": "square", "text": fechamento_texto})

                            state["adaptation"]["trades_analyzed"] += 1
                            if pnl > 0: 
                                wins += 1
                                # 🛡️ SOLUÇÃO 2: Cooldown Positivo (Descansa 1 vela de 15m se acertou)
                                cooldown_until_ts = current_ts + 900 
                            else: 
                                losses += 1
                                # 🛡️ SOLUÇÃO 2: Cooldown Punitivo (Gelo de 4 velas / 1h para evitar Overtrading em Chop Market)
                                cooldown_until_ts = current_ts + 3600 

                            state["adaptation"]["wins"] = wins
                            state["adaptation"]["losses"] = losses
                            state["adaptation"]["current_win_rate"] = round((wins / (wins + losses)) * 100, 1)
                            
                            last_trade_ts = current_ts 
                            state["entry_price"] = 0.0         
                            state["current_position"] = 0    

                        # ABERTURA DA OPERAÇÃO
                        if target_pos != 0:
                            fee = balance * FEE_RATE; balance -= fee
                            entry_price = current_price
                            
                            if target_pos == 1:
                                state["markers"].append({"time": current_ts, "position": "belowBar", "color": "#22c55e", "shape": "circle", "text": "LONG"})
                                label = "LONG 🟢"
                            else:
                                state["markers"].append({"time": current_ts, "position": "aboveBar", "color": "#ef4444", "shape": "circle", "text": "SHORT"})
                                label = "SHORT 🔴"

                            state["order_book"].insert(0, {"text": f"[{horario}] 🚀 ABRIU {label} em ${current_price:.2f}"})
                            state["in_position"] = True
                            state["entry_price"] = entry_price       
                            state["current_position"] = target_pos   
                            last_trade_ts = current_ts
                            max_profit_pct = 0.0   

                        else:
                            state["in_position"] = False
                            state["entry_price"] = 0.0         
                            state["current_position"] = 0       

                        position = target_pos

                    if not warming_up and position != 0:
                        change = (current_price - entry_price) / entry_price
                        unrealized = (balance * change) if position == 1 else (balance * -change)
                        state["status"] = f"{'🟢 LONG' if position == 1 else '🔴 SHORT'} ATIVO (PnL: ${unrealized:+.2f})"
                    elif not warming_up and act_idx == 0 and not is_choppy:
                        state["status"] = "PROCURANDO OPORTUNIDADE"

            last_100 = df_clean.tail(100)
            clean_history = []
            
            for _, row in last_100.iterrows():
                clean_history.append({
                    "time": int(row['timestamp'].timestamp()),
                    "open": float(row['open']), 
                    "high": float(row['high']), 
                    "low": float(row['low']), 
                    "close": float(row['close']),
                    "rsi": float(row['rsi']), 
                    "bb_width": float(row['bb_width']) 
                })

            state["chart_data"] = clean_history
            state["last_candle"] = clean_history[-1]
            
            state["uptime"] = get_uptime()
            state["markers"] = state["markers"][-100:] 
            
            if 'df' in locals(): del df 
            gc.collect() 
            await asyncio.sleep(5)
            await asyncio.sleep(5) 

        except Exception as e:
            print(f"❌ Erro no Loop: {e}")
            await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    path, gen = get_latest_model()
    state["adaptation"]["generation"] = gen
    load_brain(path)
    
    loop_task = asyncio.create_task(sniper_loop())
    yield
    loop_task.cancel()
    if exchange: await exchange.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

@app.get("/")
@app.head("/")
async def health_check():
    return {"status": "IA Trader Pro Backend Online e Respirando!"}

@app.get("/api/historico")
async def get_historico():
    try:
        if not exchange:
            return {"error": "Exchange não iniciada"}
        ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=1000)
        history = [{"time": int(r[0]/1000), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in ohlcv]
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download-dados")
async def download_dados(senha: str):
    admin_pass = os.environ.get("ADMIN_PASSWORD", "senha_padrao_secreta")
    if senha != admin_pass:
        raise HTTPException(status_code=403, detail="Acesso Negado: Senha Incorreta.")
    
    if not os.path.exists(DATA_PATH):
        raise HTTPException(status_code=404, detail="Nenhum dado coletado ainda.")
        
    df = pd.read_csv(DATA_PATH)
    if len(df) > 0:
        first_ts = pd.to_datetime(df.iloc[0]['timestamp'])
        last_ts = pd.to_datetime(df.iloc[-1]['timestamp'])
        hours_collected = (last_ts - first_ts).total_seconds() / 3600
        if hours_collected < 24.0:
            print(f"⚠️ Aviso: Apenas {hours_collected:.1f}h de dados coletados.")
            
    filename = f"mercado_real_{datetime.now().strftime('%Y%m%d')}.csv"
    return FileResponse(DATA_PATH, media_type='text/csv', filename=filename)

@app.post("/upload-cerebro")
async def upload_cerebro(senha: str, file: UploadFile = File(...)):
    admin_pass = os.environ.get("ADMIN_PASSWORD", "senha_padrao_secreta")
    if senha != admin_pass:
        raise HTTPException(status_code=403, detail="Acesso Negado: Senha Incorreta.")
        
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="O cérebro deve ser um arquivo .zip")

    current_gen = state["adaptation"]["generation"]
    new_gen = current_gen + 1
    new_path = f"models/sniper_pro_gen_{new_gen}.zip"
    
    with open(new_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    state["status"] = "🧠 ATUALIZANDO REDE NEURAL..."
    load_brain(new_path)
    
    global lstm_states, episode_starts, wins, losses
    lstm_states = None 
    episode_starts = np.ones((1,), dtype=bool)
    
    wins = 0
    losses = 0
    state["adaptation"]["wins"] = 0
    state["adaptation"]["losses"] = 0
    state["adaptation"]["current_win_rate"] = 0.0
    state["adaptation"]["initial_win_rate"] = 0.0
    state["adaptation"]["trades_analyzed"] = 0
    state["adaptation"]["generation"] = new_gen
    
    if os.path.exists(DATA_PATH):
        os.rename(DATA_PATH, f"data/archive_gen_{current_gen}.csv")
        
    return {"mensagem": f"Protocolo Apocalipse: Geração {new_gen} instalada com sucesso!"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print(">>> 🟢 INTERFACE DA FRONT-END CONECTADA!")
    try:
        while True:
            await websocket.send_json(state)
            await asyncio.sleep(1)
    except Exception: 
        print(">>> 🔴 Interface desconectada.")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)