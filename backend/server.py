import asyncio
import json
import time
from datetime import datetime
import pandas as pd
import numpy as np
import pandas_ta_classic as ta
import ccxt.async_support as ccxt
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from sb3_contrib import RecurrentPPO
import warnings
import gc # Garbage Collector

warnings.filterwarnings("ignore")

# --- CONFIGURAÇÕES DO APOCALIPSE ---
SYMBOL = 'BTC/USDT'
TIMEFRAME = '5m'
MODEL_PATH = "models/sniper_pro_finished.zip" 
DATA_PATH = "data/live_market_data.csv"
START_TIME = time.time()
FEE_RATE = 0.0005 

# --- VARIÁVEIS DO SIMULADOR ---
balance = 100.00
position = 0 
entry_price = 0.0
wins = 0
losses = 0

state = {
    "asset": SYMBOL,
    "is_online": True,
    "in_position": False,
    "balance": balance, 
    "status": "INICIANDO MOTORES...",
    "uptime": "00:00:00",
    "last_candle": {},
    "chart_data": [],
    "markers": [],
    "order_book": [], 
    "adaptation": {
        "generation": 1,
        "learning_state": "OBSERVANDO",
        "initial_win_rate": 0.0, # Será calculado no Backtest Inicial
        "current_win_rate": 0.0,
        "trades_analyzed": 0
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

# --- 1. SCRIPT DE BACKTEST INICIAL DA MÁQUINA ---
def run_startup_backtest(df_clean, model_instance):
    print(">>> 🔬 EXECUTANDO BACKTEST DE AQUECIMENTO (Calculando Win Rate Real)...")
    test_wins = 0
    test_losses = 0
    sim_pos = 0
    sim_entry = 0.0
    
    temp_lstm = None
    temp_ep = np.ones((1,), dtype=bool)
    
    # Isola os últimos 300 candles (aprox. 1 dia de mercado fechado) para não viciar a IA
    test_df = df_clean.tail(300)
    
    for i in range(len(test_df)):
        obs = test_df[feature_cols].iloc[i].values.astype(np.float32)
        action, temp_lstm = model_instance.predict(obs, state=temp_lstm, episode_start=temp_ep, deterministic=True)
        temp_ep = np.zeros((1,), dtype=bool)
        
        act_idx = action.item() if isinstance(action, np.ndarray) else action
        target_pos = 0
        if act_idx == 1: target_pos = 1
        elif act_idx == 2: target_pos = -1
        
        if target_pos != sim_pos:
            if sim_pos != 0:
                chg = (test_df.iloc[i]['close'] - sim_entry) / sim_entry
                pnl = chg if sim_pos == 1 else -chg
                if pnl > 0: test_wins += 1
                else: test_losses += 1
            if target_pos != 0:
                sim_entry = test_df.iloc[i]['close']
            sim_pos = target_pos
            
    tot = test_wins + test_losses
    if tot == 0: return 50.0 # Valor neutro caso ele não tenha operado no backtest
    return round((test_wins/tot)*100, 1)

def get_latest_model():
    if not os.path.exists("models"):
        os.makedirs("models")
    
    # Busca arquivos gerados pelo Protocolo Apocalipse
    files = [f for f in os.listdir("models") if f.startswith("sniper_pro_gen_") and f.endswith(".zip")]
    
    if not files:
        # Se não houver evoluções, usa o modelo base original
        return MODEL_PATH, 1
    
    # Extrai os números e encontra a maior geração
    gens = [int(f.split("_")[3].split(".")[0]) for f in files]
    latest_gen = max(gens)
    return f"models/sniper_pro_gen_{latest_gen}.zip", latest_gen

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
        # 1. Carrega os dados crus salvos pelo bot
        if not os.path.exists(DATA_PATH):
            print("❌ Erro: Arquivo de dados não encontrado para treino.")
            return None
            
        df = pd.read_csv(DATA_PATH)
        
        # 2. RECALCULA OS INDICADORES (O que estava faltando!)
        # Sem isso, a IA não encontra as colunas 'rsi', 'macd', etc.
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

        # Remove as linhas com valores nulos para o treino não bugar
        df_clean = df.dropna().copy()
        
        # 3. Cria o ambiente com os dados agora repletos de indicadores
        env = BitcoinTradingEnv(df_clean)
        
        global model
        # 4. Recarrega o modelo injetando o novo ambiente
        model = RecurrentPPO.load(MODEL_PATH, env=env, device="cpu", tensorboard_log=None)
        
        # 5. EVOLUINDO (Aprendendo com os erros e acertos reais)
        model.learn(total_timesteps=5000)
        
        # 6. Salva a nova geração
        new_path = f"models/sniper_pro_gen_{current_gen + 1}.zip"
        model.save(new_path)
        print(f">>> ✅ SUCESSO! Geração {current_gen + 1} salva em {new_path}")
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
            state["order_book"].insert(0, {"text": f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ GEN {state['adaptation']['generation']} ONLINE!"})
    except Exception as e:
        print(f"❌ Erro na Evolução: {e}")
        state["adaptation"]["learning_state"] = "FALHA NA EVOLUÇÃO."
    is_training = False

def get_uptime():
    seconds = int(time.time() - START_TIME)
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    return f"{hours:02d}:{mins:02d}:{secs:02d}"

async def sniper_loop():
    global state, exchange, lstm_states, episode_starts, is_training
    global balance, position, entry_price, wins, losses
    
    exchange = ccxt.binance({'enableRateLimit': True})
    print(f">>> 🚀 CONECTADO AO MERCADO REAL. AGUARDANDO ALVOS...")

    startup_phase = True
    startup_timer = 0
    
    # Nova lógica de estabilização (substitui o awaiting_neutral antigo)
    warming_up = True 
    warmup_counter = 0
    
    consecutive_signals = 0 
    last_signal = 0         

    while True:
        try:
            # 1. COLETA DE DADOS (1000 velas para precisão dos indicadores)
            ohlcv = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=500)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Persistência no CSV
            if os.path.exists(DATA_PATH):
                df_hist = pd.read_csv(DATA_PATH)
                df_hist = pd.concat([df_hist, df]).drop_duplicates(subset=['timestamp']).tail(5000)
                df_hist.to_csv(DATA_PATH, index=False)
            else:
                if not os.path.exists("data"): os.makedirs("data")
                df.to_csv(DATA_PATH, index=False)

            # 2. ENGENHARIA DE FEATURES
            df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
            df['rsi'] = ta.rsi(df['close'], length=14)
            df['rsi_slope'] = df['rsi'].diff()
            
            macd = ta.macd(df['close'])
            df['macd_diff'] = macd[[c for c in macd.columns if c.startswith('MACDh') or c.startswith('MACDH')][0]] if macd is not None else 0
            
            bb = ta.bbands(df['close'], length=20, std=2)
            if bb is not None:
                upper = [c for c in bb.columns if c.startswith('BBU')][0]
                lower = [c for c in bb.columns if c.startswith('BBL')][0]
                width = [c for c in bb.columns if c.startswith('BBB')][0]
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

            # 3. INFERÊNCIA E LÓGICA DE EXECUÇÃO
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
                    
                    # Predição da IA
                    action, lstm_states = model.predict(obs, state=lstm_states, episode_start=episode_starts, deterministic=True)
                    episode_starts = np.zeros((1,), dtype=bool)
                    act_idx = action.item()
                    
                    horario = datetime.now().strftime("%H:%M:%S")
                    current_price = float(last_row['close'])
                    current_ts = int(ohlcv[-1][0] / 1000) 
                    
                    target_pos = position 

                    # AQUECIMENTO TÉCNICO (Evita entradas bruscas ao ligar)
                    if warming_up:
                        warmup_counter += 1
                        state["status"] = f"🛡️ AQUECIMENTO TÉCNICO... ({warmup_counter}/10)"
                        if warmup_counter >= 10:
                            warming_up = False
                            print(">>> ✅ SISTEMA AQUECIDO E LIBERADO.")
                    
                    else:
                        # FILTRO DE CONVICÇÃO (Exige 3 sinais iguais)
                        if act_idx != 0 and act_idx == last_signal:
                            consecutive_signals += 1
                        elif act_idx != 0:
                            consecutive_signals = 1
                            last_signal = act_idx
                        else:
                            consecutive_signals = 0
                            last_signal = 0

                        if act_idx == 0: 
                            target_pos = 0 # Saída é imediata
                        elif consecutive_signals >= 3:
                            target_pos = 1 if act_idx == 1 else -1
                            consecutive_signals = 0 
                        else:
                            # Atualiza status de validação
                            sig_type = "LONG" if act_idx == 1 else "SHORT"
                            state["status"] = f"🔍 VALIDANDO {sig_type}... ({consecutive_signals}/3)"

                    # PROCESSAMENTO DE ORDENS
                    if target_pos != position:
                        # 1. Fechar posição anterior
                        if position != 0:
                            change_pct = (current_price - entry_price) / entry_price
                            pnl = (balance * change_pct) if position == 1 else (balance * -change_pct)
                            
                            fee = balance * FEE_RATE
                            balance += (pnl - fee)
                            state["balance"] = balance
                            
                            cor = "🟢" if pnl >= 0 else "🔴"
                            state["order_book"].insert(0, {"text": f"[{horario}] {cor} FECHOU POSIÇÃO | PnL: ${pnl:.2f}"})
                            state["markers"].append({"time": current_ts, "position": "inBar", "color": "#eab308", "shape": "circle", "text": "SAÍDA"})

                            state["adaptation"]["trades_analyzed"] += 1
                            if pnl > 0: wins += 1
                            else: losses += 1
                            
                            total_trades = wins + losses
                            state["adaptation"]["current_win_rate"] = round((wins / total_trades) * 100, 1)

                            if state["adaptation"]["trades_analyzed"] % 3 == 0 and not is_training:
                                asyncio.create_task(evolve_apocalypse())

                        # 2. Abrir nova posição
                        if target_pos != 0:
                            fee = balance * FEE_RATE
                            balance -= fee
                            entry_price = current_price
                            
                            if target_pos == 1:
                                state["markers"].append({"time": current_ts, "position": "belowBar", "color": "#22c55e", "shape": "arrowUp", "text": "LONG"})
                                label = "LONG 🟢"
                            else:
                                state["markers"].append({"time": current_ts, "position": "aboveBar", "color": "#ef4444", "shape": "arrowDown", "text": "SHORT"})
                                label = "SHORT 🔴"

                            state["order_book"].insert(0, {"text": f"[{horario}] 🚀 ABRIU {label} em ${current_price:.2f}"})
                            state["in_position"] = True
                        else:
                            state["in_position"] = False

                        position = target_pos

                    # ATUALIZAÇÃO DE STATUS EM TEMPO REAL
                    if not warming_up and position != 0:
                        change = (current_price - entry_price) / entry_price
                        unrealized = (balance * change) if position == 1 else (balance * -change)
                        prefix = "🟢 LONG" if position == 1 else "🔴 SHORT"
                        state["status"] = f"{prefix} ATIVO (PnL: ${unrealized:+.2f})"
                    elif not warming_up and act_idx == 0:
                        state["status"] = "PROCURANDO OPORTUNIDADE"

           # --- 4. PREPARO PARA O FRONTEND (FIM DO CICLO) ---
            clean_history = [{"time": int(r[0]/1000), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in ohlcv[-100:]]
            
            state["chart_data"] = clean_history
            state["last_candle"] = clean_history[-1]
            state["uptime"] = get_uptime()
            state["markers"] = state["markers"][-50:]
            
            # 1. Deletamos o DataFrame 'df' que criamos lá no início do loop.
            # Ele é pesado e não precisamos mais dele até a próxima rodada.
            if 'df' in locals():
                del df 
            
            # 2. Chamamos o Garbage Collector (Coletor de Lixo).
            # Isso força o Python a liberar a RAM pro sistema operacional IMEDIATAMENTE.
            gc.collect() 

            # 3. Aumentamos o descanso para 5 segundos.
            # No Render Free, a CPU é dividida com outros usuários. 
            # Se o bot rodar a cada 2s, o Render pode te "dar um puxão de orelha" por uso excessivo.
            await asyncio.sleep(5)

        except Exception as e:
            print(f"❌ Erro no Loop: {e}")
            await asyncio.sleep(10) # Se der erro, descansa mais tempo ainda


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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print(">>> 🟢 INTERFACE CONECTADA!")
    try:
        while True:
            await websocket.send_json(state); await asyncio.sleep(1)
    except Exception: print(">>> 🔴 Interface desconectada.")

if __name__ == "__main__":
    import uvicorn
    import os
    # O Render injeta a porta automaticamente nesta variável
    port = int(os.environ.get("PORT", 8000)) 
    uvicorn.run(app, host="0.0.0.0", port=port)